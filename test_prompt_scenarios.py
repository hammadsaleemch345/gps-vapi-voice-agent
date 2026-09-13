"""
Mock scenario tests for the GPS VAPI system prompt.

Runs canned caller conversations against the prompt using Anthropic's API
(claude-sonnet-4-5 by default; change MODEL to try others) and checks the
agent's response for the specific behaviors Cassidy has flagged in feedback.

Usage:
    export ANTHROPIC_API_KEY=sk-...
    source .venv/bin/activate
    python test_prompt_scenarios.py

If ANTHROPIC_API_KEY is not set, prints the scenario matrix for manual testing.
"""

import os
import sys
from pathlib import Path

PROMPT_PATH = Path(__file__).parent / "vapi_system_prompt.txt"
MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 400

# Each scenario: caller messages (in order) → agent should/should NOT do
SCENARIOS = [
    {
        "name": "Existing customer auto-detect (ants)",
        "caller_turns": [
            "Hi, you were just out for ants last week and they're back."
        ],
        "must_contain_any": ["sorry", "back", "again", "no worries", "let's"],
        "must_not_contain": [
            "new customer or existing",
            "are you a new",
            "looking for service",
        ],
        "notes": "Should skip classification question entirely",
    },
    {
        "name": "Termite intent lock",
        "caller_turns": [
            "Hi, I think I have termites in my basement."
        ],
        "must_contain_any": ["termite", "inspection"],
        "must_not_contain": [
            "what are you looking for",
            "is there something specific",
            "what can I help you with",
        ],
        "notes": "Should acknowledge termite immediately, mention free inspection",
    },
    {
        "name": "No DIY implication for termites",
        "caller_turns": [
            "I have termites eating through my deck."
        ],
        "must_not_contain": [
            "tricky to take care of yourself",
            "difficult to handle on your own",
            "hard to do yourself",
        ],
        "notes": "Never imply caller could handle it themselves",
    },
    {
        "name": "Rodent fee stated in call ($100)",
        "caller_turns": [
            "Hi, I'm a new customer. I have mice in my kitchen.",
            "About a week now, mostly under the sink.",
            "John Smith.",
            "Yes this number is fine.",
            "john at gmail dot com.",
            "1234 Oak Street, Kansas City Missouri 64105.",
            "About a 4.",
            "Yes please give me pricing.",
            "2 bathrooms.",
            "Okay, tell me more.",
            "Okay got it, what's the total?",
        ],
        "must_contain_any": ["100", "$100", "hundred"],
        "must_not_contain": [
            "the team will explain",
            "someone will go over",
            "our team will walk you through",
        ],
        "notes": "Agent must state $100 rodent fee in-call, not defer to team",
        "eval_turn": -1,
    },
    {
        "name": "No re-asking after concern stated",
        "caller_turns": [
            "Hi, I need roach service.",
        ],
        "must_not_contain": [
            "what can I help you with",
            "is there something specific",
            "what brings you in today",
        ],
        "notes": "Once caller states roach, don't re-ask what they need",
    },
    {
        "name": "Single acknowledgment (no double-stack)",
        "caller_turns": [
            "Hi I need someone out as soon as possible for ants.",
        ],
        "must_not_contain_patterns": [
            ("got it", 2),
            ("i understand", 2),
            ("makes sense", 2),
            ("absolutely", 2),
        ],
        "notes": "Don't stack two acknowledgments in one response",
    },
    {
        "name": "Existing customer preferred timing",
        "caller_turns": [
            "You were just out but the roaches are back.",
            "Jane Doe.",
            "1234 Oak Street, Kansas City Missouri 64105.",
            "Yes this number is fine.",
            "Just saw a couple this morning near the fridge.",
            "About a 3.",
        ],
        "must_contain_any": ["morning", "afternoon", "preferred", "day"],
        "notes": "Flow B must ask about preferred day/time",
        "eval_turn": -1,
    },
    {
        "name": "Never say Schendel out loud",
        "caller_turns": [
            "Hi I need help with weed control in my lawn.",
        ],
        "must_not_contain": ["Schendel", "Schendel Lawn", "Landscape"],
        "notes": "Agent silently routes to Schendel but never says the name",
    },
    {
        "name": "Concern rating normalization (7 out of 10)",
        "caller_turns": [
            "Hi, new customer. I have ants in the kitchen.",
            "John Smith.",
            "Yes this number.",
            "john at gmail dot com.",
            "1234 Oak Street, Kansas City Missouri 64105.",
            "I'd say 7 out of 10.",
        ],
        "must_not_contain": [
            "on a scale of 1 to 5",
            "could you repeat",
            "1 to 5 scale",
            "rate from 1 to 5",
        ],
        "notes": "Should accept 7/10 and normalize, not ask to restate",
        "eval_turn": -1,
    },
    {
        "name": "Address not restarted after partial",
        "caller_turns": [
            "Hi new customer, ants in kitchen.",
            "About a week now, mostly by the sink.",
            "John Smith.",
            "Yes this number is fine.",
            "john at gmail dot com.",
            "1234 Oak Street in Kansas City.",
        ],
        "must_not_contain": [
            "your full address including",
            "can you give me your full address",
            "start over with the address",
        ],
        "must_contain_any": ["state", "zip", "missouri", "kansas"],
        "notes": "Should ask only for the missing pieces (state + zip)",
        "eval_turn": -1,
    },
    {
        "name": "Classification asked when no signal (Cassidy bug #1)",
        "caller_turns": [
            "Hi, I have ants in my kitchen.",
        ],
        "must_contain_any": [
            "new customer",
            "existing customer",
            "new or existing",
        ],
        "notes": "Ambiguous caller — must ask new vs existing before starting intake",
    },
    {
        "name": "Existing customer NOT asked email or reminders (Cassidy bug #2)",
        "caller_turns": [
            "Hi, I have ants in my kitchen.",
            "Existing customer.",
            "Jane Doe.",
            "1234 Oak Street, Kansas City Missouri 64105.",
            "Yes this number is fine.",
            "About a week now, near the sink.",
            "About a 3.",
            "Morning would be great.",
        ],
        "must_not_contain": [
            "email",
            "reminders",
            "text or email",
            "prefer reminders",
        ],
        "notes": "Existing customer flow must NEVER ask email or reminder preferences",
    },
    {
        "name": "No immediate question repetition (Cassidy bug #3)",
        "caller_turns": [
            "Hi, new customer, I have ants in my kitchen.",
            "About a week now, near the sink.",
            "John Smith.",
            "Yes this number.",
            "john at gmail dot com.",
            "1234 Oak Street, Kansas City Missouri 64105.",
            "About a 3.",
        ],
        "must_not_contain_patterns": [
            ("on a scale of 1 to 5", 1),
            ("how concerned are you", 1),
        ],
        "notes": "Concern rating question must not be repeated within same or next turn",
        "eval_all_turns": True,
    },
    {
        "name": "No random 'let me know how I can help' (Cassidy bug #4)",
        "caller_turns": [
            "Hi, I have roaches in my kitchen.",
            "New customer.",
            "About a week.",
        ],
        "must_not_contain": [
            "let me know how i can help",
            "how else can i help",
            "let me know what else",
        ],
        "notes": "Never drop filler prompts after caller has answered",
        "eval_all_turns": True,
    },
    {
        "name": "Confident opening (no filler)",
        "caller_turns": [
            "Hello?",
        ],
        "must_not_contain_patterns": [
            ("uh", 1),
            ("um", 1),
            ("hmm", 1),
        ],
        "must_contain_any": ["green pest solutions"],
        "notes": "Opening must be confident with no filler sounds",
        "check_first_turn": True,
    },
]


def load_prompt():
    if not PROMPT_PATH.exists():
        print(f"ERROR: Prompt file not found at {PROMPT_PATH}")
        sys.exit(1)
    return PROMPT_PATH.read_text()


def run_scenario_live(client, prompt, scenario):
    """Run a scenario against Anthropic API and check assertions."""
    messages = []
    responses = []

    for turn in scenario["caller_turns"]:
        messages.append({"role": "user", "content": turn})
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=prompt,
            messages=messages,
        )
        agent_reply = response.content[0].text
        responses.append(agent_reply)
        messages.append({"role": "assistant", "content": agent_reply})

    # Choose what to evaluate
    if scenario.get("eval_all_turns"):
        to_check = "\n".join(responses).lower()
    else:
        eval_idx = 0 if scenario.get("check_first_turn") else scenario.get("eval_turn", -1)
        to_check = responses[eval_idx].lower()

    failures = []

    for phrase in scenario.get("must_not_contain", []):
        if phrase.lower() in to_check:
            failures.append(f'  ❌ Contains forbidden phrase: "{phrase}"')

    if scenario.get("must_contain_any"):
        if not any(p.lower() in to_check for p in scenario["must_contain_any"]):
            failures.append(
                f'  ❌ Missing one of expected phrases: {scenario["must_contain_any"]}'
            )

    for phrase, max_count in scenario.get("must_not_contain_patterns", []):
        actual = to_check.count(phrase.lower())
        if actual > max_count:
            failures.append(
                f'  ❌ "{phrase}" appears {actual} times (max {max_count})'
            )

    return responses, failures


def print_manual_matrix():
    print("\n" + "=" * 70)
    print("MANUAL TEST MATRIX (no ANTHROPIC_API_KEY set)")
    print("=" * 70)
    print("\nRun these scenarios manually via VAPI web tester and verify.\n")
    for i, s in enumerate(SCENARIOS, 1):
        print(f"\n--- Scenario {i}: {s['name']} ---")
        print(f"Notes: {s['notes']}")
        print("Caller turns:")
        for t in s["caller_turns"]:
            print(f'  → "{t}"')
        if s.get("must_contain_any"):
            print(f"Agent MUST include one of: {s['must_contain_any']}")
        if s.get("must_not_contain"):
            print(f"Agent MUST NOT say: {s['must_not_contain']}")
        if s.get("must_not_contain_patterns"):
            print("Agent MUST NOT repeat:")
            for phrase, max_count in s["must_not_contain_patterns"]:
                print(f'  - "{phrase}" more than {max_count} time(s)')


def main():
    prompt = load_prompt()
    print(f"Loaded prompt: {len(prompt)} chars from {PROMPT_PATH.name}")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n⚠️  ANTHROPIC_API_KEY not set — printing manual test matrix instead.")
        print_manual_matrix()
        return

    try:
        import anthropic
    except ImportError:
        print("Install anthropic first: pip install anthropic")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    print(f"Running {len(SCENARIOS)} scenarios against {MODEL}...\n")

    passed = 0
    failed = 0
    for i, scenario in enumerate(SCENARIOS, 1):
        print(f"[{i}/{len(SCENARIOS)}] {scenario['name']}")
        try:
            responses, failures = run_scenario_live(client, prompt, scenario)
        except Exception as e:
            print(f"  ⚠️  Error running scenario: {e}\n")
            failed += 1
            continue

        if not failures:
            print("  ✅ PASS")
            passed += 1
        else:
            print("  ❌ FAIL")
            for f in failures:
                print(f)
            # Show the offending response for debugging
            if scenario.get("eval_all_turns"):
                print(f"  Full agent output (all turns):")
                for i, r in enumerate(responses):
                    print(f"    T{i+1}: {r[:150]}...")
            else:
                eval_idx = (
                    0 if scenario.get("check_first_turn") else scenario.get("eval_turn", -1)
                )
                print(f"  Agent said: {responses[eval_idx][:200]}...")
            failed += 1
        print()

    print("=" * 70)
    print(f"Results: {passed}/{len(SCENARIOS)} passed, {failed} failed")
    print("=" * 70)


if __name__ == "__main__":
    main()
