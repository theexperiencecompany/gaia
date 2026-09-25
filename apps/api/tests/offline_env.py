"""Boot the API with no services and no vault, before any app import.

Shared by the test suite's root conftest and scripts/export_openapi.py:
both need create_app() to resolve settings from fake, hermetic values and
never dial Infisical. Everything here runs at import time by design — the
settings singleton is built the moment app.config.settings is imported,
so the environment has to be in place first.
"""

import os
from unittest.mock import patch

os.environ["ENV"] = "development"
# A dev .env's DEV_AUTH_BYPASS_EMAIL would short-circuit WorkOSAuthMiddleware here too.
# Forced empty, not popped: load_dotenv(override=False) at settings import won't
# re-inject over a key that already exists.
os.environ["DEV_AUTH_BYPASS_EMAIL"] = ""
# Same fix for other bool-typed dev overrides get_settings() resolves too early to catch.
# DEV_UNLIMITED_RATE_LIMITS causes 11 false rate-limiter failures if set; GAIA_SIM_MODE
# routes LLM calls to the stub; "" would be a pydantic bool_parsing error, so "false".
os.environ["DEV_UNLIMITED_RATE_LIMITS"] = "false"
os.environ["GAIA_SIM_MODE"] = "false"
# Code mode mints per-invocation tokens; pin it off so a developer's .env
# cannot leak execute env into hermetic bash tests. Opt in per test.
os.environ["ENABLE_CODE_MODE"] = "false"
# Same leak, opposite pin: the OpenUI experiment ships ON and the prompt-contract
# tests assert the OpenUI variant, so a developer's ENABLE_COMMS_OPENUI=false in
# .env would flip the suite's static prompts. Flag-off paths opt in per test.
os.environ["ENABLE_COMMS_OPENUI"] = "true"
# The HIL ledger ships ON too; barrier-path tests opt out via hil_barrier_mode.
os.environ["ENABLE_HIL_LEDGER"] = "true"
os.environ.setdefault(
    "MONGO_DB",
    "mongodb://localhost:27017/gaia_test?serverSelectionTimeoutMS=100&connectTimeoutMS=100",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("WORKOS_API_KEY", "sk_test_fake")
os.environ.setdefault("WORKOS_CLIENT_ID", "client_fake")
os.environ.setdefault("WORKOS_COOKIE_PASSWORD", "a" * 32)
os.environ.setdefault("RESEND_API_KEY", "re_test_fake")
os.environ.setdefault("RESEND_AUDIENCE_ID", "aud_fake")
os.environ.setdefault("EMAIL_UNSUBSCRIBE_SECRET", "test-unsubscribe-secret-" + "x" * 16)
os.environ.setdefault(
    "MCP_ENCRYPTION_KEY",
    "dGVzdF9lbmNyeXB0aW9uX2tleV8zMl9ieXRlcw==",  # pragma: allowlist secret
)
os.environ.setdefault("AGENT_SECRET", "test-agent-secret-" + "x" * 32)  # pragma: allowlist secret

# LangChain ships every graph run to LangSmith when these are truthy (a dev .env sets
# them): runs get rate-limited (429s), the exporter retries on shutdown, and every
# agent test pays the latency. Forced off (not setdefault) to override the .env.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

# Same reasoning for Langfuse: it activates only when all three of these are set
# (app/config/langfuse.py), so blanking one disables it and stops the exporter
# blocking on shutdown retrying spans against a host the suite never contacts.
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["LANGFUSE_HOST"] = ""

# chromadb's telemetry client is a background network thread that makes the process
# fork-hostile: mutmut forking a child hit SIGTRAP (exit -5) before it wrote a byte,
# so every mutant of chroma_store came back "suspicious" and was ungradeable.
os.environ["ANONYMIZED_TELEMETRY"] = "False"
# darwin getproxies() hits the non-fork-safe SystemConfiguration framework, segfaulting
# a mutmut child that builds an httpx client there. A non-empty proxy var short-circuits
# it; NO_PROXY=* is behavior-neutral — httpx returns no proxies for it either way.
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

# HOST leaks into the model's context: fetchers.py renders the public artifact URL
# from it, so a dev box's apps/api/.env value and CI's production default would
# otherwise diverge. Pinned to match the value the context snapshots were recorded against.
os.environ["HOST"] = "http://localhost:8000"

# Same reasoning for PostHog: forced off (not setdefault) before the settings import
# below, because the provider's required_keys bind at decoration time from the
# settings singleton — a developer's .env token must not leak in.
os.environ["POSTHOG_PROJECT_TOKEN"] = ""
os.environ["POSTHOG_HOST"] = ""

# Arm the Infisical fence before any app import — get_settings() runs at import time,
# so a later patch would be too late. Patching shared.py.secrets first means every
# re-export downstream (app/config/secrets.py, settings.py:25) binds the mock by construction.
_early_infisical_patch = patch("shared.py.secrets.inject_infisical_secrets", return_value=None)
_early_infisical_patch.start()
