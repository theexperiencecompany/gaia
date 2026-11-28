"""Per catalog connector: where a real key comes from, one read journey, and a safe write journey.

A write journey exists only where the provider has a sandbox the run can litter and clean:
a throwaway Resend audience, a Stripe test-mode customer, an S3 bucket on LocalStack. Nothing
ever writes to the developer's GitHub.
"""

from dataclasses import dataclass, field
import os
import subprocess

from scripts.connectors.fakes import FakeName, fake_url
from scripts.connectors.stages import WriteJourney

_AWS_REGION = "us-east-1"
_STRIPE_TEST_EMAIL = "gaia-conformance@example.com"


@dataclass(frozen=True)
class Fake:
    """How a connector's calls reach a local fake: its env, extra args, a key it accepts."""

    name: FakeName
    secret: str
    env: dict[str, str] = field(default_factory=dict)
    args: tuple[str, ...] = ()
    # The verify call to run against the fake when the spec's own cannot reach it.
    verify_args: list[str] | None = None


@dataclass(frozen=True)
class Journey:
    # Env vars a real key is read from, first set wins; "gh auth token" for the GitHub CLI.
    key_env: tuple[str, ...] = ()
    key_command: tuple[str, ...] = ()
    read: list[str] = field(default_factory=list)
    read_expect: str = ""
    write: WriteJourney | None = None
    fake: Fake | None = None
    fake_read: list[str] | None = None
    fake_write: WriteJourney | None = None
    # Why a real key would not pass today, when the team's known key is known to be dead.
    known_dead_key: str | None = None


def real_key(journey: Journey) -> tuple[str | None, str]:
    """Return the real key and where it came from, or None and the env names it was looked up in."""
    for name in journey.key_env:
        if value := os.environ.get(name):
            return value, name
    if journey.key_command:
        env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
        ran = subprocess.run(
            list(journey.key_command), capture_output=True, text=True, check=False, env=env
        )
        if ran.returncode == 0 and ran.stdout.strip():
            return ran.stdout.strip(), " ".join(journey.key_command)
    return None, " / ".join(journey.key_env) or " ".join(journey.key_command)


def _py(script: str) -> list[str]:
    return ["-c", script]


_RESEND_SDK = "import json, os, resend; resend.api_key = os.environ['RESEND_API_KEY']; "
_STRIPE_SDK = (
    "import json, os, stripe; stripe.api_key = os.environ['STRIPE_API_KEY']; "
    "stripe.api_base = os.environ.get('GAIA_FAKE_API_BASE', stripe.api_base); "
)
_BOTO3 = f"import json, boto3; s3 = boto3.client('s3', region_name='{_AWS_REGION}'); "
_LOCALSTACK = Fake(
    name=FakeName.LOCALSTACK,
    secret="test:test",
    env={"AWS_ENDPOINT_URL": fake_url(FakeName.LOCALSTACK)},
)
_S3_WRITE_CLI = WriteJourney(
    create=["s3api", "create-bucket", "--bucket", "{name}", "--region", _AWS_REGION],
    cleanup=["s3api", "delete-bucket", "--bucket", "{name}", "--region", _AWS_REGION],
    gone=["s3api", "list-buckets", "--output", "json", "--region", _AWS_REGION],
)
_S3_WRITE_BOTO3 = WriteJourney(
    create=_py(_BOTO3 + "s3.create_bucket(Bucket='{name}'); print(json.dumps({'ok': True}))"),
    cleanup=_py(_BOTO3 + "s3.delete_bucket(Bucket='{name}'); print(json.dumps({'ok': True}))"),
    gone=_py(_BOTO3 + "print(json.dumps([b['Name'] for b in s3.list_buckets()['Buckets']]))"),
)
_STRIPE_MOCK = Fake(
    name=FakeName.STRIPE_MOCK,
    secret="sk_test_123",
    env={"GAIA_FAKE_API_BASE": fake_url(FakeName.STRIPE_MOCK)},
)

JOURNEYS: dict[str, Journey] = {
    "github-cli": Journey(
        key_env=("GITHUB_CONFORMANCE_TOKEN",),
        key_command=("gh", "auth", "token"),
        read=["repo", "list", "--limit", "1", "--json", "name"],
        read_expect='"name"',
    ),
    "resend": Journey(
        key_env=("RESEND_API_KEY",),
        read=["GET", "/domains"],
        read_expect='"data"',
        write=WriteJourney(
            create=["POST", "/audiences", "--json", '{"name": "{name}"}'],
            id_path="id",
            cleanup=["DELETE", "/audiences/{id}"],
            gone=["GET", "/audiences"],
        ),
    ),
    "resend-sdk": Journey(
        key_env=("RESEND_API_KEY",),
        read=_py(_RESEND_SDK + "print(json.dumps(resend.Domains.list()))"),
        read_expect='"data"',
        write=WriteJourney(
            create=_py(
                _RESEND_SDK + "print(json.dumps(resend.Audiences.create({'name': '{name}'})))"
            ),
            id_path="id",
            cleanup=_py(_RESEND_SDK + "print(json.dumps(resend.Audiences.remove('{id}')))"),
            gone=_py(_RESEND_SDK + "print(json.dumps(resend.Audiences.list()))"),
        ),
    ),
    "cloudflare-api": Journey(
        key_env=("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_AI_API_TOKEN"),
        read=["GET", "/user/tokens/verify"],
        read_expect='"active"',
    ),
    "wrangler": Journey(
        key_env=("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_AI_API_TOKEN"),
        read=["whoami"],
        read_expect="API Token",
    ),
    "openai-api": Journey(
        key_env=("OPENAI_API_KEY",),
        read=["GET", "/models"],
        read_expect='"data"',
        known_dead_key="the team's OPENAI_API_KEY is expired",
    ),
    "openai-sdk": Journey(
        key_env=("OPENAI_API_KEY",),
        read=_py("import openai; print([m.id for m in openai.OpenAI().models.list().data][:3])"),
        read_expect="'",
        known_dead_key="the team's OPENAI_API_KEY is expired",
    ),
    "stripe-cli": Journey(
        key_env=("STRIPE_API_KEY",),
        read=["customers", "list", "--limit", "1"],
        read_expect='"object"',
        write=WriteJourney(
            create=[
                "customers",
                "create",
                "--email",
                _STRIPE_TEST_EMAIL,
                "--description",
                "{name}",
            ],
            id_path="id",
            cleanup=["customers", "delete", "{id}", "--confirm"],
            gone=["customers", "retrieve", "{id}"],
        ),
        fake=Fake(
            name=FakeName.STRIPE_MOCK,
            secret="sk_test_123",
            args=("--api-base", fake_url(FakeName.STRIPE_MOCK)),
        ),
    ),
    "stripe-sdk": Journey(
        key_env=("STRIPE_API_KEY",),
        read=_py(_STRIPE_SDK + "print(json.dumps(stripe.Customer.list(limit=1)))"),
        read_expect='"object"',
        write=WriteJourney(
            create=_py(
                _STRIPE_SDK
                + f"print(json.dumps(stripe.Customer.create(email='{_STRIPE_TEST_EMAIL}', description='{{name}}')))"
            ),
            id_path="id",
            cleanup=_py(_STRIPE_SDK + "print(json.dumps(stripe.Customer.delete('{id}')))"),
            gone=_py(_STRIPE_SDK + "print(json.dumps(stripe.Customer.retrieve('{id}')))"),
        ),
        fake=_STRIPE_MOCK,
    ),
    "aws-cli": Journey(
        key_env=("AWS_CONFORMANCE_KEY",),
        read=["s3api", "list-buckets", "--output", "json", "--region", _AWS_REGION],
        read_expect='"Buckets"',
        fake=_LOCALSTACK,
        fake_write=_S3_WRITE_CLI,
    ),
    "boto3": Journey(
        key_env=("AWS_CONFORMANCE_KEY",),
        read=_py(_BOTO3 + "print(json.dumps(s3.list_buckets()['Buckets'], default=str))"),
        read_expect="[",
        fake=_LOCALSTACK,
        fake_write=_S3_WRITE_BOTO3,
    ),
    "vercel-cli": Journey(key_env=("VERCEL_TOKEN",), read=["projects", "ls"], read_expect=""),
    "flyctl": Journey(key_env=("FLY_API_TOKEN",), read=["apps", "list", "--json"], read_expect="["),
    "supabase-cli": Journey(
        key_env=("SUPABASE_ACCESS_TOKEN",), read=["projects", "list", "-o", "json"], read_expect="["
    ),
    "doppler-cli": Journey(
        key_env=("DOPPLER_TOKEN",), read=["projects", "--json"], read_expect="["
    ),
    "railway-cli": Journey(
        key_env=("RAILWAY_API_TOKEN", "RAILWAY_TOKEN"), read=["whoami"], read_expect=""
    ),
    "heroku-cli": Journey(key_env=("HEROKU_API_KEY",), read=["apps", "--json"], read_expect="["),
    "netlify-cli": Journey(
        key_env=("NETLIFY_AUTH_TOKEN",), read=["sites:list", "--json"], read_expect="["
    ),
    "twilio": Journey(
        key_env=("TWILIO_CONFORMANCE_KEY",),
        read=["GET", "/2010-04-01/Accounts.json"],
        read_expect='"accounts"',
    ),
    "sendgrid": Journey(
        key_env=("SENDGRID_API_KEY",), read=["GET", "/scopes"], read_expect='"scopes"'
    ),
    "postmark": Journey(
        key_env=("POSTMARK_SERVER_TOKEN",), read=["GET", "/server"], read_expect='"Name"'
    ),
    "digitalocean": Journey(
        key_env=("DIGITALOCEAN_TOKEN",), read=["GET", "/account"], read_expect='"account"'
    ),
    "sentry": Journey(
        key_env=("SENTRY_AUTH_TOKEN",), read=["GET", "/organizations/"], read_expect="["
    ),
    "render": Journey(key_env=("RENDER_API_KEY",), read=["GET", "/owners"], read_expect="["),
    "hetzner-cloud": Journey(
        key_env=("HCLOUD_TOKEN",), read=["GET", "/servers"], read_expect='"servers"'
    ),
}
