"""
GPS VAPI Server — CDK Stack

Resources:
  - Lambda function (Python 3.12, stdlib only)
  - Lambda Function URL (public, no auth — VAPI needs direct POST access)
  - IAM policy for SES send
  - SES domain identities with DKIM for both brand domains
"""

import os

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_ses as ses,
)
from constructs import Construct


class GpsVapiStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------
        # Config — override via cdk.json context or environment variables
        # ------------------------------------------------------------------
        email_from = self.node.try_get_context("email_from") or "messages@gpspest.com"
        gps_inbox = self.node.try_get_context("gps_inbox") or "messages@gpspest.com"
        schendel_inbox = self.node.try_get_context("schendel_inbox") or "messages@schendellawn.com"
        vapi_secret = self.node.try_get_context("vapi_secret") or os.environ.get("VAPI_SECRET", "")
        if not vapi_secret:
            raise ValueError("VAPI_SECRET must be set via cdk context or env var")

        # ------------------------------------------------------------------
        # Lambda Function
        # ------------------------------------------------------------------
        webhook_fn = _lambda.Function(
            self,
            "VapiWebhook",
            function_name="gps-vapi-webhook",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="lambda_function.lambda_handler",
            code=_lambda.Code.from_asset("runtime"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "EMAIL_FROM": email_from,
                "GPS_INBOX": gps_inbox,
                "SCHENDEL_INBOX": schendel_inbox,
                "AWS_REGION_SES": self.region,
                "VAPI_SECRET": vapi_secret,
            },
            description="GPS Voice Assistant — handles VAPI webhook events",
        )

        # ------------------------------------------------------------------
        # SES Permissions
        # ------------------------------------------------------------------
        webhook_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=["*"],
                effect=iam.Effect.ALLOW,
            )
        )

        # ------------------------------------------------------------------
        # Lambda Function URL (public — VAPI sends POST directly)
        # ------------------------------------------------------------------
        fn_url = webhook_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[_lambda.HttpMethod.POST, _lambda.HttpMethod.GET],
                allowed_headers=["*"],
            ),
        )

        # ------------------------------------------------------------------
        # SES Domain Identities (DKIM-signed — prevents spam classification)
        # ------------------------------------------------------------------
        gps_domain = ses.EmailIdentity(
            self,
            "GpsDomainIdentity",
            identity=ses.Identity.domain("gpspest.com"),
        )

        schendel_domain = ses.EmailIdentity(
            self,
            "SchendelDomainIdentity",
            identity=ses.Identity.domain("schendellawn.com"),
        )

        # ------------------------------------------------------------------
        # Outputs
        # ------------------------------------------------------------------
        CfnOutput(
            self,
            "FunctionUrl",
            value=fn_url.url,
            description="Lambda Function URL — set this as your VAPI Server URL",
        )

        CfnOutput(
            self,
            "FunctionName",
            value=webhook_fn.function_name,
            description="Lambda function name",
        )

        CfnOutput(
            self,
            "FunctionArn",
            value=webhook_fn.function_arn,
            description="Lambda function ARN",
        )

        CfnOutput(
            self,
            "GpsDkimRecords",
            value="Check SES console for gpspest.com DKIM CNAME records",
            description="Add the 3 DKIM CNAME records to gpspest.com DNS",
        )

        CfnOutput(
            self,
            "SchendelDkimRecords",
            value="Check SES console for schendellawn.com DKIM CNAME records",
            description="Add the 3 DKIM CNAME records to schendellawn.com DNS",
        )
