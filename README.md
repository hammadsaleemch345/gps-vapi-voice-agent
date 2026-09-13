# GPS Voice Assistant — VAPI Webhook Server

Python Lambda server for GPS Pest Solutions voice assistant. Handles VAPI webhook events, routes emails to GPS/Schendel inboxes via AWS SES. Infrastructure defined with AWS CDK.

## Project Structure

```
gps-vapi-server/
├── app.py                      # CDK app entry point
├── cdk.json                    # CDK config + context values
├── requirements.txt            # CDK dependencies
├── requirements-dev.txt        # Local dev dependencies
├── .env.example                # Local env template
├── infra/
│   ├── __init__.py
│   └── stack.py                # CDK stack (Lambda, Function URL, SES, IAM)
├── runtime/
│   └── lambda_function.py      # Lambda handler + local Flask server
├── tests/
│   └── test_local.py           # Integration tests
└── vapi_tool_definitions.json  # VAPI tool configs
```

## What Gets Deployed

- **Lambda function** (`gps-vapi-webhook`) — Python 3.12, 256MB, 30s timeout
- **Function URL** — public endpoint, no auth (VAPI needs direct POST access)
- **IAM policy** — SES send permissions on the Lambda role
- **SES email identities** — sender address + both brand inboxes (triggers verification emails)

## Local Development

```bash
# 1. Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

# 2. Run server
cd runtime
python lambda_function.py

# 3. Run tests (in another terminal)
cd tests
python test_local.py

# 4. Test Lambda handler directly (no Flask)
python test_local.py --lambda
```

## Deploy with CDK

### Prerequisites

1. AWS CLI configured: `aws configure` (region: us-east-1)
2. Node.js installed (CDK requirement)
3. CDK installed: `npm install -g aws-cdk`
4. IAM user has AdministratorAccess

### First Time Setup

```bash
# Install CDK dependencies
pip install -r requirements.txt

# Bootstrap CDK in your account (one time only)
cdk bootstrap aws://YOUR_ACCOUNT_ID/us-east-1
```

### Deploy

```bash
# Preview what will be created
cdk diff

# Deploy
cdk deploy
```

CDK will output the **Function URL**. That's your VAPI Server URL.

### Custom Config

Edit `cdk.json` to change email addresses, or pass context at deploy time:

```bash
cdk deploy -c email_from=notifications@gpspest.com -c vapi_secret=your-secret
```

## After Deploy

### 1. Verify SES Emails

CDK creates SES identities but each address needs to click a verification link. Check the inbox for:
- `noreply@gpspest.com` (sender)
- `messages@gpspest.com` (GPS inbox)
- `messages@schendellawn.com` (Schendel inbox)

### 2. Connect to VAPI

1. Copy the Function URL from CDK output
2. VAPI Dashboard → Assistant → Advanced → Server URL → paste URL
3. Enable server messages: `tool-calls`, `end-of-call-report`, `status-update`, `hang`
4. Add tools from `vapi_tool_definitions.json` (replace `YOUR_LAMBDA_FUNCTION_URL` with your actual URL)

### 3. Test

Make a test call through VAPI and verify:
- Email arrives at the correct inbox
- Subject line format is correct
- All caller info is captured

## Useful Commands

```bash
cdk deploy          # Deploy stack
cdk diff            # Preview changes
cdk destroy         # Tear down stack
cdk synth           # Generate CloudFormation template
```

## Tear Down

```bash
cdk destroy
```

Removes Lambda, Function URL, IAM role, and SES identities. Clean removal, nothing left running.
