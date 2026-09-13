#!/usr/bin/env python3
"""CDK app entry point for GPS VAPI Server."""

import aws_cdk as cdk
from infra.stack import GpsVapiStack

app = cdk.App()

GpsVapiStack(
    app,
    "GpsVapiStack",
    env=cdk.Environment(region="us-east-1"),
    description="GPS Voice Assistant — VAPI webhook server with Lambda + SES",
)

app.synth()
