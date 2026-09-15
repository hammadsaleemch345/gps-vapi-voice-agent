"""
GPS Voice Assistant — VAPI Webhook Server
Works both as AWS Lambda handler AND local Flask dev server.

Usage:
  Local:  python lambda_function.py
  Lambda: handler = lambda_handler (set in AWS console)
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Config (set these as Lambda environment variables or in .env for local)
# ---------------------------------------------------------------------------

def _parse_email_list(value: str, default: str) -> list:
    raw = value or default
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


EMAIL_FROM = os.getenv("EMAIL_FROM", "noreply@gpspest.com")
GPS_INBOX = _parse_email_list(os.getenv("GPS_INBOX", ""), "messages@gpspest.com")
SCHENDEL_INBOX = _parse_email_list(os.getenv("SCHENDEL_INBOX", ""), "messages@schendellawn.com")
AWS_REGION_SES = os.getenv("AWS_REGION_SES", "us-east-1")

VAPI_SECRET = os.getenv("VAPI_SECRET", "")
VAPI_DASHBOARD_CALL_URL = "https://dashboard.vapi.ai/calls/{call_id}"

def get_ct_offset() -> timedelta:
    """Return current CT offset accounting for DST (CDT=-5, CST=-6)."""
    import time
    return timedelta(hours=-5) if time.daylight and time.localtime().tm_isdst else timedelta(hours=-6)

# SES client (initialized lazily to support both Lambda and local)
_ses_client = None

def get_ses_client():
    global _ses_client
    if _ses_client is None:
        import boto3
        _ses_client = boto3.client("ses", region_name=AWS_REGION_SES)
    return _ses_client


_WORD_TO_NUM = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000,
}

_TENS = {20, 30, 40, 50, 60, 70, 80, 90}
_MAGNITUDE_WORDS = {"hundred", "thousand"}

_ORDINAL_MAP = {
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th",
    "fifth": "5th", "sixth": "6th", "seventh": "7th", "eighth": "8th",
    "ninth": "9th", "tenth": "10th", "eleventh": "11th", "twelfth": "12th",
    "thirteenth": "13th", "fourteenth": "14th", "fifteenth": "15th",
    "sixteenth": "16th", "seventeenth": "17th", "eighteenth": "18th",
    "nineteenth": "19th", "twentieth": "20th", "thirtieth": "30th",
    "fortieth": "40th", "fiftieth": "50th", "sixtieth": "60th",
    "seventieth": "70th", "eightieth": "80th", "ninetieth": "90th",
    "hundredth": "100th",
}

_DIRECTION_MAP = {
    "north": "N", "south": "S", "east": "E", "west": "W",
    "northeast": "NE", "northwest": "NW", "southeast": "SE", "southwest": "SW",
}

_STREET_TYPE_MAP = {
    "street": "St", "avenue": "Ave", "boulevard": "Blvd", "road": "Rd",
    "drive": "Dr", "lane": "Ln", "court": "Ct", "place": "Pl",
    "parkway": "Pkwy", "highway": "Hwy", "circle": "Cir", "terrace": "Ter",
}

_STATE_MAP = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "wisconsin": "WI", "wyoming": "WY",
    # Multi-word states — matched via _MULTI_WORD_STATES pass
}

_MULTI_WORD_STATES = {
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "south carolina": "SC",
    "south dakota": "SD", "west virginia": "WV", "rhode island": "RI",
}


def _words_to_int(words):
    """Convert a list of number words into a single integer (e.g. ['twenty','ninth']-style handled elsewhere)."""
    total = 0
    current = 0
    for w in words:
        if w not in _WORD_TO_NUM:
            return None
        n = _WORD_TO_NUM[w]
        if n == 100 or n == 1000:
            current = max(current, 1) * n
            total += current
            current = 0
        else:
            current += n
    return total + current


def _collapse_ordinal_compound(tokens):
    """Handle 'twenty-ninth' style (two words joined by hyphen or spaces)."""
    out = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if "-" in tok:
            parts = tok.split("-")
            if len(parts) == 2 and parts[0] in _WORD_TO_NUM and parts[1] in _ORDINAL_MAP:
                base = _WORD_TO_NUM[parts[0]]
                ord_suffix = _ORDINAL_MAP[parts[1]]
                digits = "".join(c for c in ord_suffix if c.isdigit())
                total = base + int(digits)
                out.append(f"{total}{ord_suffix[-2:]}")
                i += 1
                continue
        if i + 1 < len(tokens) and tok in _WORD_TO_NUM and tokens[i + 1] in _ORDINAL_MAP:
            base = _WORD_TO_NUM[tok]
            ord_suffix = _ORDINAL_MAP[tokens[i + 1]]
            digits = "".join(c for c in ord_suffix if c.isdigit())
            total = base + int(digits)
            out.append(f"{total}{ord_suffix[-2:]}")
            i += 2
            continue
        out.append(tok)
        i += 1
    return out


def _group_compounds(run):
    """Merge tens+unit pairs into single values so spoken groups survive:
    ['sixty', 'four', 'thirty', 'three'] -> [64, 33]
    ['eleven', 'oh', 'one'] -> [11, 0, 1]
    """
    groups = []
    i = 0
    while i < len(run):
        value = _WORD_TO_NUM[run[i]]
        has_unit_next = i + 1 < len(run) and 1 <= _WORD_TO_NUM[run[i + 1]] <= 9
        if value in _TENS and has_unit_next:
            value += _WORD_TO_NUM[run[i + 1]]
            i += 2
        else:
            i += 1
        groups.append(value)
    return groups


def _collapse_number_run(tokens):
    """Collapse consecutive number-word tokens.
    - Magnitude words present -> arithmetic ("four thousand one hundred" -> 4100)
    - One spoken group -> its value ("twenty one" -> 21)
    - Several groups -> concatenate, the way US house numbers, ZIPs and phones are
      spoken ("sixty four thirty three" -> 6433, "eleven oh one" -> 1101,
      "six six six one one" -> 66611)
    """
    out = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok not in _WORD_TO_NUM:
            out.append(tok)
            i += 1
            continue

        run = []
        j = i
        while j < len(tokens) and tokens[j] in _WORD_TO_NUM:
            run.append(tokens[j])
            j += 1

        if any(w in _MAGNITUDE_WORDS for w in run):
            value = _words_to_int(run)
            out.append(str(value) if value is not None else " ".join(run))
        else:
            groups = _group_compounds(run)
            out.append("".join(str(g) for g in groups))
        i = j
    return out


def _abbreviate_states(tokens):
    """Abbreviate a state name unless it is part of a city name ("Kansas City")."""
    out = []
    for i, tok in enumerate(tokens):
        next_is_city = i + 1 < len(tokens) and tokens[i + 1] == "city"
        out.append(tok if next_is_city else _STATE_MAP.get(tok, tok))
    return out


def normalize_numbers(text: str, field: str) -> str:
    """Convert spelled-out numbers, ordinals, directions, and street types to
    their standard postal digit/abbreviation forms. Rule-based, deterministic,
    no external dependencies.
    """
    if not text:
        return text
    original = text
    try:
        import re
        # Multi-word state pass first (case-insensitive) so "New York" becomes "NY"
        # before tokenization can split it.
        working = text
        for phrase, abbr in _MULTI_WORD_STATES.items():
            working = re.sub(rf"\b{phrase}\b(?!\s+city\b)", abbr, working, flags=re.IGNORECASE)
        text = working
        # Tokenize while preserving simple punctuation. Keep alphanumeric tokens
        # like "40th" and "12A" as single tokens so we don't split off suffixes.
        raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]*|\d+[A-Za-z]*|[.,]", text)
        # Preserve original case for uppercase-only abbreviations like "MO", "KS"
        preserve_upper = {t for t in raw_tokens if t.isupper() and 2 <= len(t) <= 3}
        tokens = [t.lower() for t in raw_tokens]

        # Ordinal compounds first (twenty-ninth -> 29th)
        tokens = _collapse_ordinal_compound(tokens)
        # Simple ordinals (ninth -> 9th)
        tokens = [_ORDINAL_MAP.get(t, t) for t in tokens]
        # Number runs (eleven oh one -> 1101, six six six one one -> 66611)
        tokens = _collapse_number_run(tokens)
        # Directions, street types, and single-word states
        tokens = [_DIRECTION_MAP.get(t, t) for t in tokens]
        tokens = [_STREET_TYPE_MAP.get(t, t) for t in tokens]
        tokens = _abbreviate_states(tokens)

        # Rebuild string — capitalize first letter of each non-abbreviation word
        rebuilt = []
        abbrevs = set(list(_DIRECTION_MAP.values()) + list(_STREET_TYPE_MAP.values()))
        for tok in tokens:
            if tok in (".", ","):
                if rebuilt:
                    rebuilt[-1] = rebuilt[-1] + tok
            elif tok.upper() in preserve_upper:
                rebuilt.append(tok.upper())
            elif tok in abbrevs or tok.isdigit() or any(c.isdigit() for c in tok):
                rebuilt.append(tok)
            elif len(tok) <= 2 and tok.upper() == tok:
                rebuilt.append(tok)
            else:
                rebuilt.append(tok.capitalize())
        result = " ".join(rebuilt)
        # Phone: strip everything except digits and +
        if field == "phone number":
            digits = re.sub(r"[^\d+]", "", result)
            if len(digits) == 10:
                digits = "+1" + digits
            elif len(digits) == 11 and digits.startswith("1"):
                digits = "+" + digits
            return digits or original
        if result and result != text:
            logger.info(f"Normalized {field}: {original!r} -> {result!r}")
            return result
    except Exception as e:
        logger.warning(f"normalize_numbers({field}) failed: {e}")
    return original


# ---------------------------------------------------------------------------
# Brand Detection
# ---------------------------------------------------------------------------

SCHENDEL_KEYWORDS = [
    "lawn", "fertilization", "fertilize", "weed control", "weed",
    "aeration", "aerate", "sprinkler", "sprinklers", "irrigation",
    "turf", "vegetation", "grass", "mowing", "landscaping", "landscape",
    "yard treatment", "yard", "sod", "overseeding", "seeding",
]


def detect_brand(text: str) -> str:
    if not text:
        return "gps"
    lower = text.lower()
    for kw in SCHENDEL_KEYWORDS:
        if kw in lower:
            return "schendel"
    return "gps"


def get_brand_email(brand: str) -> list:
    return SCHENDEL_INBOX if brand == "schendel" else GPS_INBOX


# ---------------------------------------------------------------------------
# Time-Aware Callback Language
# ---------------------------------------------------------------------------

def get_current_ct() -> datetime:
    return datetime.now(timezone.utc) + get_ct_offset()


def get_callback_language() -> str:
    ct_now = get_current_ct()
    hour = ct_now.hour
    minute = ct_now.minute
    weekday = ct_now.weekday()
    time_decimal = hour + minute / 60.0

    if weekday >= 5:
        return "We'll follow up next business day."
    if 7.5 <= time_decimal < 15.5:
        return "We'll call you back within about an hour."
    if 15.5 <= time_decimal < 17.0:
        return "It may be next business day since we're wrapping up, but we'll get back to you quickly."
    return "We'll follow up next business day."


# ---------------------------------------------------------------------------
# Emergency Classification
# ---------------------------------------------------------------------------

EMERGENCY_KEYWORDS = [
    "emergency", "raccoon", "bat", "bats", "squirrel", "squirrels",
    "wildlife inside", "stinging", "wasp inside", "bee inside",
    "wasps inside", "bees inside", "urgent",
]


def classify_emergency(text: str, concern_rating: int = 0) -> bool:
    if not text:
        return False
    lower = text.lower()
    for kw in EMERGENCY_KEYWORDS:
        if kw in lower:
            return True
    return concern_rating >= 4


# ---------------------------------------------------------------------------
# Pricing Engine (v1.1)
# ---------------------------------------------------------------------------

THRIVE_QUARTERLY = {
    "1-2": 93, "2.5-3": 101, "3.5-4": 110,
    "4.5-5": 120, "5.5": 142, "6+": 150,
}
THRIVE_MONTHLY = {
    "1-2": 76, "2.5-3": 84, "3.5-4": 91,
    "4.5-5": 102, "5.5": 124, "6+": 130,
}
THRIVE_ECO_QUARTERLY = {
    "1-2": 117, "2.5-3": 127, "3.5-4": 137,
    "4.5-5": 151, "5.5": 178, "6+": 222,
}
THRIVE_ECO_MONTHLY = {
    "1-2": 95, "2.5-3": 105, "3.5-4": 114,
    "4.5-5": 128, "5.5": 155, "6+": 206,
}

PRICING_TABLES = {
    ("thrive", "quarterly"): THRIVE_QUARTERLY,
    ("thrive", "monthly"): THRIVE_MONTHLY,
    ("thrive_eco", "quarterly"): THRIVE_ECO_QUARTERLY,
    ("thrive_eco", "monthly"): THRIVE_ECO_MONTHLY,
}

ONE_TIME_PEST_FEE = 100
ANNUAL_DISCOUNT_PCT = 5
QUARTERLY_ACTIVATION_FEE = 50
MONTHLY_ACTIVATION_FEE = 50
MONTHLY_ON_QUARTERLY_ACTIVATION_FEE = 150


def resolve_bathroom_tier(bathroom_str: str) -> tuple:
    """Convert bathroom count string to pricing tier key. Returns (tier, is_minimum)."""
    try:
        val = float(str(bathroom_str).replace("+", "").strip())
    except (ValueError, TypeError):
        return "1-2", False
    if val <= 2:
        return "1-2", False
    elif val <= 3:
        return "2.5-3", False
    elif val <= 4:
        return "3.5-4", False
    elif val <= 5:
        return "4.5-5", False
    elif val <= 5.5:
        return "5.5", False
    else:
        return "6+", True


def calculate_quote(bathroom_count: str, program: str = "thrive",
                    cadence: str = "quarterly", one_time_pests: list = None) -> dict:
    """Calculate a full pricing breakdown."""
    one_time_pests = one_time_pests or []
    tier, is_minimum = resolve_bathroom_tier(bathroom_count)

    table = PRICING_TABLES.get((program, cadence))
    if not table:
        return {"error": f"Invalid program/cadence: {program}/{cadence}"}

    per_period = table[tier]
    multiplier = 4 if cadence == "quarterly" else 12
    annual_price = per_period * multiplier

    # One-time pest fees
    one_time_fees = [{"pest": p, "fee": ONE_TIME_PEST_FEE} for p in one_time_pests]
    one_time_total = len(one_time_pests) * ONE_TIME_PEST_FEE

    # Payment options
    discount_amount = round(annual_price * ANNUAL_DISCOUNT_PCT / 100, 2)
    discounted_annual = round(annual_price - discount_amount, 2)

    payment_options = {
        "annual_prepay": {
            "annual_total": discounted_annual,
            "one_time_fees": one_time_total,
            "total_due_today": round(discounted_annual + one_time_total, 2),
            "discount_pct": ANNUAL_DISCOUNT_PCT,
            "activation_fee": 0,
            "note": "Best value — 5% discount, no activation fee",
        },
        "quarterly": {
            "per_quarter": per_period,
            "one_time_fees": one_time_total,
            "activation_fee": QUARTERLY_ACTIVATION_FEE,
            "total_due_today": per_period + one_time_total + QUARTERLY_ACTIVATION_FEE,
            "note": "Billed quarterly, card charged day after service",
        },
    }

    if cadence == "quarterly":
        monthly_amount = round(annual_price / 12, 2)
        payment_options["monthly"] = {
            "per_month": monthly_amount,
            "one_time_fees": one_time_total,
            "activation_fee": MONTHLY_ON_QUARTERLY_ACTIVATION_FEE,
            "total_due_today": round(monthly_amount + one_time_total + MONTHLY_ON_QUARTERLY_ACTIVATION_FEE, 2),
            "note": "Monthly payments on quarterly service — $150 activation fee",
        }
    else:
        payment_options["monthly"] = {
            "per_month": per_period,
            "one_time_fees": one_time_total,
            "activation_fee": MONTHLY_ACTIVATION_FEE,
            "total_due_today": per_period + one_time_total + MONTHLY_ACTIVATION_FEE,
            "note": "Billed monthly",
        }

    # Eco upgrade comparison (only if quoting thrive standard)
    eco_upgrade = None
    if program == "thrive":
        eco_table = PRICING_TABLES.get(("thrive_eco", cadence))
        if eco_table:
            eco_per_period = eco_table[tier]
            eco_annual = eco_per_period * multiplier
            eco_discounted = round(eco_annual - (eco_annual * ANNUAL_DISCOUNT_PCT / 100), 2)
            eco_upgrade = {
                "program": "Thrive Eco",
                "per_period": eco_per_period,
                "annual_price": eco_annual,
                "annual_prepay_total": eco_discounted,
                "difference_per_period": eco_per_period - per_period,
                "difference_annual": eco_annual - annual_price,
            }

    program_name = "Thrive Eco" if program == "thrive_eco" else "Thrive Residential"
    return {
        "program": program_name,
        "cadence": cadence,
        "bathroom_tier": tier,
        "per_period_price": per_period,
        "annual_price": annual_price,
        "is_minimum": is_minimum,
        "one_time_fees": one_time_fees,
        "one_time_total": one_time_total,
        "payment_options": payment_options,
        "eco_upgrade": eco_upgrade,
    }


def tool_get_quote(args: dict) -> dict:
    bathroom_count = args.get("bathroom_count", "2")
    program = args.get("program", "thrive")
    cadence = args.get("cadence", "quarterly")
    one_time_pests = args.get("one_time_pests", [])

    if program not in ("thrive", "thrive_eco"):
        return {"error": "Only Thrive and Thrive Eco residential programs can be quoted."}
    if cadence not in ("quarterly", "monthly"):
        return {"error": "Cadence must be 'quarterly' or 'monthly'."}

    return calculate_quote(bathroom_count, program, cadence, one_time_pests)


# ---------------------------------------------------------------------------
# Email Builder
# ---------------------------------------------------------------------------

def build_subject_line(caller_name, intent_tags, is_emergency=False, requested_human=False, brand="gps"):
    prefix = "[GPS]" if brand == "gps" else "[SCHENDEL]"
    tags = []
    if is_emergency:
        tags.append("[EMERGENCY]")
    if requested_human:
        tags.append("[REQUESTED HUMAN]")
    for tag in intent_tags:
        formatted = f"[{tag.upper()}]"
        if formatted not in tags:
            tags.append(formatted)
    tag_str = " ".join(tags)
    name = caller_name if caller_name else "Unknown Caller"
    return f"{prefix} {tag_str} — {name}".strip()


def build_email_body(d: dict) -> str:
    body = f"""BRIEF SUMMARY
{d.get('summary', 'No summary available.')}

KEY DETAILS
Name: {d.get('caller_name', 'Not provided')}
Phone: {d.get('phone', 'Not provided')}
Email: {d.get('email', 'Not provided')}
Address: {d.get('address', 'Not provided')}
Concern: {d.get('concern_description', 'Not provided')}
Emergency: {'Yes' if d.get('is_emergency') else 'No'}
Concern Rating: {d.get('concern_rating', 'N/A')}
Preferred Appointment Window: {d.get('preferred_appointment', 'Not provided')}
Callback Expectation: {d.get('callback_language', get_callback_language())}
Service Reminder Preference: {d.get('service_reminders', 'Not provided')}
"""
    if d.get("notes"):
        body += f"\nNOTES\n{d['notes']}\n"
    if d.get("transcript_url"):
        body += f"\nTRANSCRIPT\n{d['transcript_url']}\n"
    if d.get("recording_url") or d.get("call_id"):
        body += "\nRECORDING\n"
        if d.get("recording_url"):
            body += f"{d['recording_url']}\n"
        if d.get("call_id"):
            body += f"View in VAPI: {VAPI_DASHBOARD_CALL_URL.format(call_id=d['call_id'])}\n"
    return body


def send_email(to_addresses, subject: str, body: str) -> bool:
    """Send email via AWS SES. Accepts a string or list of recipients."""
    if isinstance(to_addresses, str):
        to_addresses = [to_addresses]
    try:
        ses = get_ses_client()
        response = ses.send_email(
            Source=EMAIL_FROM,
            Destination={"ToAddresses": to_addresses},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )
        message_id = response.get("MessageId", "")
        logger.info(f"Email sent via SES to {to_addresses} | MessageId: {message_id} | Subject: {subject}")
        return True
    except ImportError:
        logger.warning("boto3 not available. Email logged only.")
        logger.info(f"TO: {to_addresses}\nSUBJECT: {subject}\nBODY:\n{body}")
        return False
    except Exception as e:
        logger.error(f"SES email failed: {e}")
        logger.info(f"TO: {to_addresses}\nSUBJECT: {subject}\nBODY:\n{body}")
        return False


# ---------------------------------------------------------------------------
# Tool Call Handlers
# ---------------------------------------------------------------------------

def handle_tool_call(tool_call: dict) -> dict:
    func = tool_call.get("function", {})
    name = func.get("name", "")
    args = func.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}

    tool_call_id = tool_call.get("id", "")
    logger.info(f"Tool call: {name} | Args: {json.dumps(args)}")

    handlers = {
        "send_summary_email": tool_send_summary_email,
        "detect_brand": tool_detect_brand,
        "get_callback_message": tool_get_callback_message,
        "check_emergency": tool_check_emergency,
        "get_quote": tool_get_quote,
    }

    handler = handlers.get(name)
    if handler:
        result = handler(args)
    else:
        result = {"error": f"Unknown function: {name}"}

    return {
        "results": [{
            "toolCallId": tool_call_id,
            "result": json.dumps(result) if isinstance(result, dict) else str(result),
        }]
    }


def tool_send_summary_email(args: dict) -> dict:
    """No-op acknowledgment. The single email is sent by handle_end_of_call_report,
    which uses these tool-call args as the source of truth (merged with transcript
    and recording URL). This prevents duplicate emails while preserving the model's
    collected data.
    """
    caller_name = args.get("caller_name", "Unknown")
    logger.info(f"send_summary_email captured for {caller_name} — will be delivered on end-of-call event")
    return {"status": "captured", "message": "Summary will be sent at end of call."}


def tool_detect_brand(args: dict) -> dict:
    text = args.get("description", "")
    brand = detect_brand(text)
    return {"brand": brand, "inbox": get_brand_email(brand)}


def tool_get_callback_message(args: dict) -> dict:
    return {"message": get_callback_language()}


def tool_check_emergency(args: dict) -> dict:
    text = args.get("description", "")
    rating = int(args.get("concern_rating", 0) or 0)
    return {"is_emergency": classify_emergency(text, rating)}


# ---------------------------------------------------------------------------
# End-of-Call Report Handler
# ---------------------------------------------------------------------------

def _extract_from_transcript(transcript: str) -> dict:
    """Regex-based fallback extractor. Parses AI/User transcript lines and pulls
    structured fields when the model failed to pass them via send_summary_email.
    """
    import re

    if not transcript:
        return {}

    lines = transcript.splitlines()
    result = {}

    def pairs():
        for i in range(len(lines) - 1):
            ai_line = lines[i].strip()
            user_line = lines[i + 1].strip()
            if ai_line.lower().startswith("ai:") and user_line.lower().startswith("user:"):
                yield ai_line[3:].strip(), user_line[5:].strip()

    def find_answer(ai_keywords):
        for ai, user in pairs():
            ai_low = ai.lower()
            if all(k in ai_low for k in ai_keywords):
                return user
        return ""

    # Concern description — first user statement usually contains the issue
    for line in lines:
        if line.lower().startswith("user:"):
            text = line[5:].strip()
            if text and len(text) > 4:
                result["concern_description"] = text
                break

    # Name — prefer the answer to a direct ask, fall back to a volunteered
    # "my name is X" anywhere in the caller's lines
    name_ans = find_answer(["first", "last", "name"])
    if name_ans:
        m = re.search(r"(?:name is|it's|i am|i'm)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", name_ans)
        if m:
            result["caller_name"] = m.group(1)
        else:
            words = [w for w in name_ans.split() if w[:1].isalpha()]
            if words:
                result["caller_name"] = " ".join(words[-2:]) if len(words) >= 2 else words[-1]
    if not result.get("caller_name"):
        for line in lines:
            if not line.lower().startswith("user:"):
                continue
            m = re.search(r"\b(?i:my name is|this is|i am|i'm)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", line[5:].strip())
            if m:
                result["caller_name"] = m.group(1)
                break

    # Email
    email_ans = find_answer(["email"])
    if email_ans:
        # Handle "at the rate of" and "dot" phrasing
        cleaned = email_ans.lower()
        cleaned = re.sub(r"\bat the rate of\b|\bat\b", "@", cleaned)
        cleaned = re.sub(r"\bdot\b", ".", cleaned)
        cleaned = re.sub(r"\s+", "", cleaned)
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", cleaned)
        if m:
            result["email"] = m.group(0)

    # Address — get everything after "address" question
    addr_ans = find_answer(["address"])
    if addr_ans:
        result["address"] = addr_ans

    # Concern rating (1-5) — accept digits, "N out of 10", or spelled-out words
    rating_ans = find_answer(["scale", "concerned"])
    if rating_ans:
        low = rating_ans.lower()
        m = re.search(r"\b([1-5])\b", rating_ans)
        if m:
            result["concern_rating"] = int(m.group(1))
        else:
            m = re.search(r"\b(\d+)\s*(?:out of|/)\s*10\b", rating_ans)
            if m:
                n = int(m.group(1))
                result["concern_rating"] = min(5, max(1, round(n / 2)))
            else:
                spelled = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
                for word, val in spelled.items():
                    if re.search(rf"\b{word}\b", low):
                        result["concern_rating"] = val
                        break

    # Preferred appointment
    appt_ans = find_answer(["preferred", "morning", "afternoon"])
    if appt_ans:
        result["preferred_appointment"] = appt_ans

    # Service reminders
    reminder_ans = find_answer(["reminders", "text", "email", "both"])
    if reminder_ans:
        low = reminder_ans.lower()
        if "both" in low:
            result["service_reminders"] = "both"
        elif "text" in low:
            result["service_reminders"] = "text"
        elif "email" in low:
            result["service_reminders"] = "email"

    return result


def _extract_summary_from_messages(messages: list) -> dict:
    """Scan the call's message array for the model's send_summary_email tool call
    and return its args as a dict. This gives us the model's collected data as
    source of truth, since it interacted with the caller directly.
    """
    if not messages:
        return {}
    for msg in messages:
        # VAPI emits assistant messages with toolCalls array
        tool_calls = msg.get("toolCalls") or msg.get("tool_calls") or []
        if isinstance(msg.get("toolCall"), dict):
            tool_calls = [msg["toolCall"]]
        for tc in tool_calls:
            fn = tc.get("function", {}) or {}
            if fn.get("name") == "send_summary_email":
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if isinstance(args, dict) and args:
                    return args
    return {}


def _pick_recording_url(artifact: dict) -> str:
    """Return the first populated recording URL.

    VAPI gated direct storage URLs in Sep 2026. Only the presigned fields open
    without a VAPI login, and they expire at artifact['presignedUrlsExpiresAt'].
    The rest are kept as fallbacks for older payload shapes.
    """
    recording = artifact.get("recording") if isinstance(artifact.get("recording"), dict) else {}
    mono = recording.get("mono") if isinstance(recording.get("mono"), dict) else {}
    candidates = (
        artifact.get("presignedStereoUrl"),
        artifact.get("presignedMonoUrl"),
        artifact.get("recordingUrl"),
        artifact.get("stereoRecordingUrl"),
        recording.get("stereoUrl"),
        mono.get("combinedUrl"),
        recording.get("url"),
    )
    return next((url for url in candidates if url), "")


def handle_end_of_call_report(payload: dict) -> dict:
    message = payload.get("message", {})
    call = message.get("call", {})
    artifact = message.get("artifact", {})
    analysis = message.get("analysis", {})
    messages = message.get("messages") or artifact.get("messages") or []

    call_id = call.get("id", "unknown")
    ended_reason = message.get("endedReason", "unknown")
    logger.info(f"End of call — ID: {call_id}, Reason: {ended_reason}")

    transcript_text = artifact.get("transcript", "")
    recording_url = _pick_recording_url(artifact)
    transcript_url = artifact.get("transcriptUrl", "")
    logger.info(f"Recording url: {recording_url[:120] if recording_url else 'EMPTY'} | presigned expires: {artifact.get('presignedUrlsExpiresAt', 'n/a')}")

    # PRIMARY source: the model's send_summary_email tool call args
    tool_args = _extract_summary_from_messages(messages)
    # FALLBACK 1: VAPI's post-call structuredData
    sd = analysis.get("structuredData", {})
    # FALLBACK 2: transcript-based regex extraction (last-resort safety net)
    from_transcript = _extract_from_transcript(transcript_text)

    def pick(field, default=""):
        return tool_args.get(field) or sd.get(field) or from_transcript.get(field) or default

    caller_name = pick("caller_name")
    phone = pick("phone")
    email_addr = pick("email")
    address = pick("address")
    concern = pick("concern_description")
    concern_rating = int(pick("concern_rating", 0) or 0)
    preferred_appt = pick("preferred_appointment")
    service_reminders = pick("service_reminders")
    intent_tags = tool_args.get("intent_tags") or sd.get("intent_tags") or []
    requested_human = bool(tool_args.get("requested_human") or sd.get("requested_human") or False)

    # Fallback phone from call metadata
    if not phone:
        phone = call.get("customer", {}).get("number", "")

    # Normalize spelled-out numbers to digits (address + phone) for care team copy-paste
    if address and address != "Not provided":
        address = normalize_numbers(address, "address")
    if phone and any(c.isalpha() for c in phone):
        phone = normalize_numbers(phone, "phone number")

    brand = detect_brand(concern)
    is_emergency = classify_emergency(concern, concern_rating)

    # Handle disconnects
    notes = tool_args.get("notes") or ""
    if ended_reason in ["customer-ended-call", "customer-did-not-give-microphone-permission"]:
        if not caller_name and not email_addr:
            notes = (notes + " Caller disconnected before full info provided.").strip()

    call_data = {
        "call_id": call_id,
        "summary": tool_args.get("summary") or analysis.get("summary") or f"Call ID: {call_id}. {concern or 'No description captured.'}",
        "caller_name": caller_name or "Unknown",
        "phone": phone,
        "email": email_addr,
        "address": address or "Not provided",
        "concern_description": concern,
        "is_emergency": is_emergency,
        "concern_rating": concern_rating,
        "preferred_appointment": preferred_appt,
        "callback_language": get_callback_language(),
        "service_reminders": service_reminders,
        "transcript_url": transcript_url,
        "recording_url": recording_url,
        "notes": notes,
    }

    # Only mark unclassified when we truly have no signal — never overwrite a real classification
    if not intent_tags:
        if caller_name or concern or address:
            # We have real data but no explicit tags — infer from concern
            inferred = []
            if is_emergency:
                inferred.append("EMERGENCY")
            if requested_human:
                inferred.append("REQUESTED HUMAN")
            inferred.append("RESIDENTIAL")
            intent_tags = inferred
        else:
            intent_tags = ["URGENT — AI COULD NOT CLASSIFY"]

    subject = build_subject_line(caller_name, intent_tags, is_emergency, requested_human, brand)
    body = build_email_body(call_data)

    if transcript_text:
        body += f"\n\nFULL TRANSCRIPT\n{'=' * 50}\n{transcript_text}\n"

    send_email(get_brand_email(brand), subject, body)
    return {"status": "processed", "call_id": call_id}


# ---------------------------------------------------------------------------
# Core Request Router
# ---------------------------------------------------------------------------

def route_request(payload: dict, headers: dict = None) -> dict:
    """Route a VAPI webhook payload to the correct handler. Returns (body, status_code)."""
    headers = headers or {}

    # Auth check
    if VAPI_SECRET:
        auth = headers.get("authorization", headers.get("Authorization", ""))
        token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
        secret = headers.get("x-vapi-secret", headers.get("X-Vapi-Secret", ""))
        if token != VAPI_SECRET and secret != VAPI_SECRET:
            return {"error": "Unauthorized"}, 401

    message = payload.get("message", {})
    msg_type = message.get("type", "")
    logger.info(f"VAPI event: {msg_type}")

    # Tool calls
    if msg_type == "tool-calls":
        tool_calls = message.get("toolCallList", []) or message.get("toolCalls", [])
        if not tool_calls:
            tc = message.get("toolCall") or message.get("functionCall")
            if tc:
                tool_calls = [tc]
        results = []
        for tc in tool_calls:
            r = handle_tool_call(tc)
            results.extend(r.get("results", []))
        return {"results": results}, 200

    # Legacy function call
    if msg_type == "function-call":
        fc = message.get("functionCall", {})
        return handle_tool_call(fc), 200

    # End of call report
    if msg_type == "end-of-call-report":
        return handle_end_of_call_report(payload), 200

    # Assistant request
    if msg_type == "assistant-request":
        logger.info("Assistant request — no dynamic routing configured")
        return {}, 200

    # Status update
    if msg_type == "status-update":
        status = message.get("status", "")
        cid = message.get("call", {}).get("id", "")
        logger.info(f"Call {cid} status: {status}")
        return {"status": "ok"}, 200

    # Hang
    if msg_type == "hang":
        logger.warning("Hang notification")
        return {"status": "ok"}, 200

    # Transcript
    if msg_type == "transcript":
        return {"status": "ok"}, 200

    # Catch all
    logger.info(f"Unhandled event: {msg_type}")
    return {"status": "ok"}, 200


# ===========================================================================
# AWS LAMBDA HANDLER
# ===========================================================================

def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    Works with API Gateway (REST & HTTP), Lambda Function URL, and ALB.
    """
    logger.info(f"Lambda event received")

    # Parse body
    body = event.get("body", "{}")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {}

    # Get headers
    headers = event.get("headers", {}) or {}

    # Health check
    http_method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("path") or event.get("rawPath", "")

    if http_method == "GET" and path in ["/health", "/", ""]:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "healthy", "service": "gps-vapi-server", "version": "1.0"}),
        }

    # Route the webhook
    result, status_code = route_request(body, headers)

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result),
    }


# ===========================================================================
# LOCAL DEV SERVER (Flask)
# ===========================================================================

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
        # Reload env vars after dotenv
        globals().update({
            "EMAIL_FROM": os.getenv("EMAIL_FROM", "noreply@gpspest.com"),
            "GPS_INBOX": _parse_email_list(os.getenv("GPS_INBOX", ""), "messages@gpspest.com"),
            "SCHENDEL_INBOX": _parse_email_list(os.getenv("SCHENDEL_INBOX", ""), "messages@schendellawn.com"),
            "AWS_REGION_SES": os.getenv("AWS_REGION_SES", "us-east-1"),
            "VAPI_SECRET": os.getenv("VAPI_SECRET", ""),
        })
    except ImportError:
        pass

    from flask import Flask, request as flask_request, jsonify

    app = Flask(__name__)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    @app.route("/vapi/webhook", methods=["POST"])
    def webhook():
        payload = flask_request.get_json(silent=True) or {}
        headers = dict(flask_request.headers)
        result, status_code = route_request(payload, headers)
        return jsonify(result), status_code

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "healthy", "service": "gps-vapi-server", "version": "1.0"})

    port = int(os.getenv("PORT", "8000"))
    print(f"\n  GPS VAPI Server running locally on http://localhost:{port}")
    print(f"  Webhook endpoint: http://localhost:{port}/vapi/webhook")
    print(f"  Health check:     http://localhost:{port}/health\n")
    app.run(host="0.0.0.0", port=port, debug=True)
