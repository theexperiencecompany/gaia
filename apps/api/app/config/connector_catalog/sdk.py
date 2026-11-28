"""Catalog connectors that run a script against a provider's pinned SDK."""

from app.config.connector_catalog.row import CatalogRow

_AWS_CREDENTIALS = (
    "[default]\naws_access_key_id = {secret_user}\naws_secret_access_key = {secret_password}\n"
)

SDK_CONNECTORS: list[CatalogRow] = [
    CatalogRow(
        id="openai-sdk",
        name="OpenAI Python SDK",
        description=(
            "OpenAI's official Python SDK for GPT models, embeddings, images and audio. GAIA "
            "can run Python scripts that call your OpenAI account through the SDK."
        ),
        spec={
            "kind": "sdk",
            "provider_domain": "openai.com",
            "capability": "Run Python scripts against your OpenAI account with the official SDK",
            "sdk_runtime": "python",
            "install": [{"manager": "pip", "name": "openai", "version": "3.60.0"}],
            "credential": {
                "env": ["OPENAI_API_KEY"],
                "label": "OpenAI API key",
                "token_url": "https://platform.openai.com/api-keys",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "OpenAI() reads OPENAI_API_KEY itself. Use client.responses.create(model, "
                    "input), client.embeddings.create(model, input), client.files.list() and "
                    "client.batches.list(); print results with .model_dump_json()."
                )
            },
            "allowed_hosts": ["api.openai.com"],
            "verify": {
                "args": [
                    "-c",
                    "from openai import OpenAI; print(OpenAI().get('/me', cast_to=str))",
                ],
                "identity": {"json_path": "email"},
            },
        },
    ),
    CatalogRow(
        id="stripe-sdk",
        name="Stripe Python SDK",
        description=(
            "Stripe's official Python SDK for payments, customers and subscriptions. GAIA can "
            "run Python scripts that read and manage your Stripe account through the SDK."
        ),
        spec={
            "kind": "sdk",
            "provider_domain": "stripe.com",
            "capability": "Run Python scripts against your Stripe account with the official SDK",
            "sdk_runtime": "python",
            "install": [{"manager": "pip", "name": "stripe", "version": "17.1.0"}],
            "credential": {
                "env": ["STRIPE_API_KEY"],
                "label": "Secret key",
                "token_url": "https://dashboard.stripe.com/apikeys",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "The SDK does not read the env itself: start with stripe.api_key = "
                    "os.environ['STRIPE_API_KEY']. Use stripe.Customer.list(limit=10), "
                    "stripe.Charge.list(), stripe.Subscription.list() and stripe.Balance.retrieve(); "
                    "print results with json.dumps(obj.to_dict())."
                )
            },
            "allowed_hosts": ["api.stripe.com", "files.stripe.com"],
            "verify": {
                "args": [
                    "-c",
                    "import json, os, stripe; stripe.api_key = os.environ['STRIPE_API_KEY']; "
                    "print(json.dumps(stripe.Account.retrieve().to_dict()))",
                ],
                "identity": {"json_path": "settings.dashboard.display_name"},
            },
        },
    ),
    CatalogRow(
        id="boto3",
        name="AWS SDK for Python (boto3)",
        description=(
            "boto3 is Amazon's official Python SDK for every AWS service. GAIA can run Python "
            "scripts that read and manage your AWS resources, such as S3, EC2 and Lambda."
        ),
        spec={
            "kind": "sdk",
            "provider_domain": "amazonaws.com",
            "capability": "Run Python scripts against your AWS account with boto3",
            "sdk_runtime": "python",
            "install": [{"manager": "pip", "name": "boto3", "version": "1.44.13"}],
            "credential": {
                "files": [{"path": "~/.aws/credentials", "template": _AWS_CREDENTIALS}],
                "label": "Access key",
                "token_url": "https://console.aws.amazon.com/iam/home#/security_credentials",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "The key is ACCESS_KEY_ID:SECRET_ACCESS_KEY and boto3 reads it from "
                    "~/.aws/credentials. No region is configured: pass region_name to every "
                    "boto3.client(...). Print results with json.dumps(response, default=str)."
                )
            },
            "allowed_hosts": ["*.amazonaws.com"],
            "verify": {
                "args": [
                    "-c",
                    "import boto3, json; print(json.dumps(boto3.client('sts', "
                    "region_name='us-east-1').get_caller_identity(), default=str))",
                ],
                "identity": {"json_path": "Arn"},
            },
        },
    ),
    CatalogRow(
        id="resend-sdk",
        name="Resend Python SDK",
        description=(
            "Resend's official Python SDK for its developer email API. GAIA can run Python "
            "scripts that send email and manage your domains, audiences and contacts."
        ),
        spec={
            "kind": "sdk",
            "provider_domain": "resend.com",
            "capability": "Run Python scripts that send email and manage domains with Resend",
            "sdk_runtime": "python",
            "install": [{"manager": "pip", "name": "resend", "version": "2.56.2"}],
            "credential": {
                "env": ["RESEND_API_KEY"],
                "label": "Resend API key",
                "token_url": "https://resend.com/api-keys",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "Start with resend.api_key = os.environ['RESEND_API_KEY']. Use "
                    "resend.Emails.send({from, to, subject, html}), resend.Domains.list(), "
                    "resend.Audiences.list() and resend.Contacts.list(audience_id=...); results "
                    "are dicts, so print them with json.dumps."
                )
            },
            "allowed_hosts": ["api.resend.com"],
            "verify": {
                "args": [
                    "-c",
                    "import json, os, resend; resend.api_key = os.environ['RESEND_API_KEY']; "
                    "print(json.dumps(resend.Domains.list()))",
                ],
                "identity": {"json_path": "data.0.name"},
            },
        },
    ),
]
