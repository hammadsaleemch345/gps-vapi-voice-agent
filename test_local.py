"""
Local test script — simulates VAPI webhook events against your server.

Usage:
  1. Start the server:  python lambda_function.py
  2. In another terminal: python test_local.py
"""

import json
import os
import sys

try:
    import requests
except ImportError:
    print("Install requests first: pip install requests")
    sys.exit(1)

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
HEADERS = {"x-vapi-secret": os.getenv("VAPI_SECRET", "")}


def test_health():
    print("\n=== Test: Health Check ===")
    r = requests.get(f"{BASE_URL}/health")
    print(f"Status: {r.status_code}")
    print(f"Response: {r.json()}")
    assert r.status_code == 200


def test_tool_detect_brand_gps():
    print("\n=== Test: Brand Detection (GPS) ===")
    payload = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [{
                "id": "tc_001",
                "function": {
                    "name": "detect_brand",
                    "arguments": {"description": "I have ants in my kitchen and mice in the attic"}
                }
            }]
        }
    }
    r = requests.post(f"{BASE_URL}/vapi/webhook", json=payload, headers=HEADERS)
    print(f"Status: {r.status_code}")
    result = r.json()
    print(f"Response: {json.dumps(result, indent=2)}")
    parsed = json.loads(result["results"][0]["result"])
    assert parsed["brand"] == "gps"
    print("PASS — brand is GPS")


def test_tool_detect_brand_schendel():
    print("\n=== Test: Brand Detection (Schendel) ===")
    payload = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [{
                "id": "tc_002",
                "function": {
                    "name": "detect_brand",
                    "arguments": {"description": "I need help with lawn fertilization and weed control"}
                }
            }]
        }
    }
    r = requests.post(f"{BASE_URL}/vapi/webhook", json=payload, headers=HEADERS)
    result = r.json()
    parsed = json.loads(result["results"][0]["result"])
    assert parsed["brand"] == "schendel"
    print(f"Response: {json.dumps(parsed, indent=2)}")
    print("PASS — brand is Schendel")


def test_tool_check_emergency():
    print("\n=== Test: Emergency Check ===")
    payload = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [{
                "id": "tc_003",
                "function": {
                    "name": "check_emergency",
                    "arguments": {"description": "There is a raccoon inside my house", "concern_rating": 5}
                }
            }]
        }
    }
    r = requests.post(f"{BASE_URL}/vapi/webhook", json=payload, headers=HEADERS)
    result = r.json()
    parsed = json.loads(result["results"][0]["result"])
    assert parsed["is_emergency"] == True
    print(f"Response: {json.dumps(parsed, indent=2)}")
    print("PASS — flagged as emergency")


def test_tool_callback_message():
    print("\n=== Test: Callback Message ===")
    payload = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [{
                "id": "tc_004",
                "function": {
                    "name": "get_callback_message",
                    "arguments": {}
                }
            }]
        }
    }
    r = requests.post(f"{BASE_URL}/vapi/webhook", json=payload, headers=HEADERS)
    result = r.json()
    parsed = json.loads(result["results"][0]["result"])
    print(f"Callback message: {parsed['message']}")
    print("PASS")


def test_tool_send_email():
    print("\n=== Test: Send Summary Email (no SMTP = queued) ===")
    payload = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [{
                "id": "tc_005",
                "function": {
                    "name": "send_summary_email",
                    "arguments": {
                        "caller_name": "John Smith",
                        "phone": "555-123-4567",
                        "email": "john@example.com",
                        "address": "123 Main St, Kansas City, KS 66101",
                        "concern_description": "Ants in kitchen and garage",
                        "concern_rating": 2,
                        "preferred_appointment": "Tuesday morning",
                        "service_reminders": "Text",
                        "intent_tags": ["NEW CUSTOMER", "RESIDENTIAL"],
                        "requested_human": False,
                        "summary": "New residential customer reports ant issue in kitchen and garage."
                    }
                }
            }]
        }
    }
    r = requests.post(f"{BASE_URL}/vapi/webhook", json=payload, headers=HEADERS)
    result = r.json()
    parsed = json.loads(result["results"][0]["result"])
    print(f"Response: {json.dumps(parsed, indent=2)}")
    assert parsed["brand"] == "gps"
    assert "[NEW CUSTOMER]" in parsed["subject"]
    print("PASS — email queued with correct subject")


def test_tool_send_email_schendel_emergency():
    print("\n=== Test: Schendel Emergency Email ===")
    payload = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [{
                "id": "tc_006",
                "function": {
                    "name": "send_summary_email",
                    "arguments": {
                        "caller_name": "Jane Doe",
                        "phone": "555-987-6543",
                        "email": "jane@example.com",
                        "address": "456 Oak Ave, Overland Park, KS 66212",
                        "concern_description": "Emergency — wildlife inside my house, also need lawn weed control",
                        "concern_rating": 5,
                        "preferred_appointment": "ASAP",
                        "intent_tags": ["NEW CUSTOMER"],
                        "requested_human": True,
                        "summary": "Schendel caller with emergency wildlife issue and lawn care needs."
                    }
                }
            }]
        }
    }
    r = requests.post(f"{BASE_URL}/vapi/webhook", json=payload, headers=HEADERS)
    result = r.json()
    parsed = json.loads(result["results"][0]["result"])
    print(f"Response: {json.dumps(parsed, indent=2)}")
    assert parsed["brand"] == "schendel"
    assert parsed["is_emergency"] == True
    assert "[EMERGENCY]" in parsed["subject"]
    assert "[REQUESTED HUMAN]" in parsed["subject"]
    print("PASS — Schendel emergency with human request")


def test_end_of_call_report():
    print("\n=== Test: End-of-Call Report ===")
    payload = {
        "message": {
            "type": "end-of-call-report",
            "endedReason": "assistant-ended-call",
            "call": {
                "id": "call_abc123",
                "customer": {"number": "+15551234567"}
            },
            "artifact": {
                "transcript": "AI: Hello, thank you for calling GPS Pest Solutions...\nUser: Hi, I have ants...",
                "recording": {"url": "https://recordings.vapi.ai/abc123.wav"},
                "transcriptUrl": "https://transcripts.vapi.ai/abc123",
                "messages": []
            },
            "analysis": {
                "summary": "New residential customer called about ant problem in kitchen.",
                "structuredData": {
                    "caller_name": "Mike Johnson",
                    "phone": "+15551234567",
                    "email": "mike@example.com",
                    "address": "789 Elm St, Wichita, KS 67202",
                    "concern_description": "Ants in kitchen for the past week",
                    "concern_rating": 3,
                    "preferred_appointment": "Wednesday afternoon",
                    "intent_tags": ["NEW CUSTOMER", "RESIDENTIAL"],
                    "requested_human": False,
                    "is_emergency": False,
                    "service_reminders": "Both"
                }
            }
        }
    }
    r = requests.post(f"{BASE_URL}/vapi/webhook", json=payload, headers=HEADERS)
    result = r.json()
    print(f"Response: {json.dumps(result, indent=2)}")
    assert result["status"] == "processed"
    assert result["call_id"] == "call_abc123"
    print("PASS — end of call report processed")


def test_status_update():
    print("\n=== Test: Status Update ===")
    payload = {
        "message": {
            "type": "status-update",
            "status": "in-progress",
            "call": {"id": "call_abc123"}
        }
    }
    r = requests.post(f"{BASE_URL}/vapi/webhook", json=payload, headers=HEADERS)
    assert r.status_code == 200
    print("PASS")


def test_lambda_handler_directly():
    """Test the lambda_handler function without Flask."""
    print("\n=== Test: Lambda Handler Directly ===")
    from lambda_function import lambda_handler

    # Simulate API Gateway event
    event = {
        "httpMethod": "POST",
        "path": "/vapi/webhook",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "message": {
                "type": "tool-calls",
                "toolCallList": [{
                    "id": "tc_lambda_001",
                    "function": {
                        "name": "detect_brand",
                        "arguments": {"description": "I need sprinkler irrigation help"}
                    }
                }]
            }
        })
    }

    response = lambda_handler(event, None)
    print(f"Status: {response['statusCode']}")
    body = json.loads(response["body"])
    parsed = json.loads(body["results"][0]["result"])
    print(f"Brand: {parsed['brand']}")
    assert parsed["brand"] == "schendel"
    print("PASS — Lambda handler works directly")

    # Test health check
    health_event = {"httpMethod": "GET", "path": "/health", "headers": {}}
    health_response = lambda_handler(health_event, None)
    assert health_response["statusCode"] == 200
    print("PASS — Lambda health check works")


if __name__ == "__main__":
    if "--lambda" in sys.argv:
        # Test lambda handler directly (no Flask needed)
        test_lambda_handler_directly()
    else:
        # Test against running Flask server
        print("Testing against local Flask server at", BASE_URL)
        print("Make sure 'python lambda_function.py' is running first.\n")

        try:
            test_health()
            test_tool_detect_brand_gps()
            test_tool_detect_brand_schendel()
            test_tool_check_emergency()
            test_tool_callback_message()
            test_tool_send_email()
            test_tool_send_email_schendel_emergency()
            test_end_of_call_report()
            test_status_update()

            print("\n" + "=" * 50)
            print("ALL TESTS PASSED")
            print("=" * 50)
        except requests.ConnectionError:
            print("\nERROR: Could not connect to server.")
            print("Start the server first: python lambda_function.py")
            sys.exit(1)
        except AssertionError as e:
            print(f"\nTEST FAILED: {e}")
            sys.exit(1)
