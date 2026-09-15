"""Boot the API with no services and no vault, before any ``app`` import.

Shared by the test suite's root conftest and ``scripts/export_openapi.py``:
both need ``create_app()`` to resolve settings from fake, hermetic values and
never dial Infisical. Everything here runs at import time by design — the
settings singleton is built the moment ``app.config.settings`` is imported,
so the environment has to be in place first.
"""

import os
from unittest.mock import patch

os.environ["ENV"] = "development"
# Force the dev auth bypass OFF for the suite: a machine set up for agent-driven
# e2e has DEV_AUTH_BYPASS_EMAIL in apps/api/.env, which would short-circuit
# WorkOSAuthMiddleware — including in the tests that exercise that middleware.
# Force an empty (falsy) value rather than popping: an empty value keeps the
# prod-guard off, and because the key is now present, load_dotenv(override=False)
# — called at settings import — will not re-inject a value from the developer's .env.
os.environ["DEV_AUTH_BYPASS_EMAIL"] = ""
# Same problem, same fix, for the other dev overrides that change behaviour
# rather than carry a secret — the credential fence below never sees them
# because they are not credential-shaped, and it would run too late anyway:
# get_settings() is lru_cached and already resolved during collection.
# DEV_UNLIMITED_RATE_LIMITS lifts the limits the rate-limiter tests assert (11
# false failures on a machine that sets it); GAIA_SIM_MODE routes every LLM
# call to the local stub. Both are typed `bool`, so the neutral value must be
# parseable — "" is a pydantic bool_parsing error, not an "off".
os.environ["DEV_UNLIMITED_RATE_LIMITS"] = "false"
os.environ["GAIA_SIM_MODE"] = "false"
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

# LangChain ships every graph run to LangSmith when these are truthy, and a
# developer's .env turns them on. That makes the suite depend on an external
# service it never asserts against: runs get rate-limited (429s), the exporter
# retries on shutdown, and each agent test pays the latency. Forced off rather
# than setdefault — the point is to override the .env, not defer to it.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

# Same reasoning for Langfuse, which activates only when all three of these are
# set (app/config/langfuse.py) — so blanking one disables it. A developer's .env
# supplies them, and the exporter then blocks on shutdown retrying spans against
# a host the suite has no business contacting.
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
os.environ["LANGFUSE_HOST"] = ""

# chromadb phones home on every client start and collection create, and its
# telemetry client is a background thread doing network I/O. Beyond being an
# external call the suite never asserts on, that thread is what makes the
# process fork-hostile: mutmut re-runs a test file inside a fork, and the
# child died on SIGTRAP (exit -5) before writing a byte, so every mutant of
# chroma_store came back "suspicious" and the module could never be graded.
os.environ["ANONYMIZED_TELEMETRY"] = "False"
# darwin getproxies() falls through to the SystemConfiguration framework
# (_scproxy), which is not fork-safe: mutmut forks a child per mutant, and any
# child that builds an httpx client segfaults inside that native call, leaving
# the mutant without a verdict. A non-empty proxy var makes
# getproxies_environment() truthy and short-circuits the native path, and
# NO_PROXY=* is behavior-neutral: httpx returns no proxies for it, which is
# what a hermetic suite gets on Linux anyway.
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

# HOST leaks into the model's context: fetchers.py renders the public artifact
# URL from it, so the effective prompt — and the recorded context snapshots —
# differ between a dev box with apps/api/.env (localhost) and CI without one
# (the production default). Pinned so the rendered context is the same
# everywhere; the snapshots were recorded against this value.
os.environ["HOST"] = "http://localhost:8000"

# Same reasoning for PostHog: analytics capture must never reach a live
# project from the suite. Forced off (not setdefault) BEFORE the settings
# import below — the provider's required_keys are bound at decoration time
# from the settings singleton, so a developer's .env token must not leak in.
os.environ["POSTHOG_PROJECT_TOKEN"] = ""
os.environ["POSTHOG_HOST"] = ""

# Arm the Infisical fence BEFORE any app import: settings.py calls get_settings()
# at import time (via the module-level `settings` singleton), and the import
# chain below (payment_models -> ... -> app.config.settings) would dial the real
# vault before any later patch could intercept. shared.py.secrets imports
# cleanly, so patching its binding first means every re-export downstream
# (app/config/secrets.py, settings.py:25) binds the mock by construction.
_early_infisical_patch = patch("shared.py.secrets.inject_infisical_secrets", return_value=None)
_early_infisical_patch.start()
