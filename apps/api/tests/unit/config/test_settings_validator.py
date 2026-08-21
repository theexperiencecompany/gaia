"""The registered settings groups, exercised through a fresh validator.

The module-level ``settings_validator`` singleton registers its groups at
import time, so nothing that only imports the module ever runs the
registration again. These tests construct their own validator, which is what
makes the registration observable at all — and what lets the mutation gate
reach a verdict on it.
"""

from types import SimpleNamespace
from typing import NamedTuple

import pytest

from app.config.settings import CommonSettings
from app.config.settings_validator import SettingsGroup, SettingsValidator
from tests.helpers import captured_wide_event

POSTHOG_GROUP = "Posthog Analytics"
POSTHOG_FIELDS = {name for name in CommonSettings.model_fields if name.startswith("POSTHOG_")}


class _ExpectedGroup(NamedTuple):
    """One predefined group's exact expected fields, in registration order."""

    name: str
    keys: list[str]
    description: str
    affected_features: str
    required_in_prod: bool
    all_required: bool
    docs_url: str | None
    alternative_group: str | None


# The full, in-order registration list `_register_predefined_groups()` builds.
# Every field of every group is asserted exactly below, so a mutated string,
# a flipped boolean, or an altered key list on any group fails a test.
EXPECTED_GROUPS: list[_ExpectedGroup] = [
    _ExpectedGroup(
        "MongoDB Connection",
        ["MONGO_DB"],
        "MongoDB database connection",
        "All database operations, user data, and application state",
        True,
        True,
        "https://www.mongodb.com/docs/manual/reference/connection-string/",
        None,
    ),
    _ExpectedGroup(
        "Redis Connection",
        ["REDIS_URL"],
        "Redis cache and queue service",
        "Caching, rate limiting, and task scheduling",
        True,
        True,
        "https://redis.io/docs/connect/clients/",
        None,
    ),
    _ExpectedGroup(
        "PostgreSQL Connection",
        ["POSTGRES_URL"],
        "PostgreSQL database connection",
        "Relational data storage and queries",
        True,
        True,
        "https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING",
        None,
    ),
    _ExpectedGroup(
        "ChromaDB Connection",
        ["CHROMADB_HOST", "CHROMADB_PORT"],
        "ChromaDB vector database connection",
        "Vector storage and semantic search capabilities",
        True,
        True,
        "https://docs.trychroma.com/",
        None,
    ),
    _ExpectedGroup(
        "RabbitMQ Connection",
        ["RABBITMQ_URL"],
        "RabbitMQ message queue connection",
        "Asynchronous task processing and job queue",
        True,
        True,
        "https://www.rabbitmq.com/uri-spec.html",
        None,
    ),
    _ExpectedGroup(
        "WorkOS Authentication",
        ["WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD"],
        "WorkOS authentication service",
        "User authentication, login, and session management",
        True,
        True,
        "https://workos.com/docs/reference/api-keys",
        None,
    ),
    _ExpectedGroup(
        "Cloudinary Media Storage",
        ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"],
        "Cloudinary media storage service",
        "File uploads, image storage, and support ticket attachments",
        True,
        True,
        "https://cloudinary.com/documentation/cloudinary_credentials",
        None,
    ),
    _ExpectedGroup(
        "Speech Processing",
        ["DEEPGRAM_API_KEY"],
        "Speech-to-text transcription service",
        "Audio transcription and voice interaction",
        True,
        False,
        "https://deepgram.com/",
        None,
    ),
    _ExpectedGroup(
        "OpenAI Integration",
        ["OPENAI_API_KEY"],
        "OpenAI API integration (alternative to Google AI)",
        "AI chat, text generation, and language processing",
        True,
        True,
        "https://platform.openai.com/api-keys",
        "Google AI",
    ),
    _ExpectedGroup(
        "Google AI",
        ["GOOGLE_API_KEY"],
        "Google AI services (alternative to OpenAI)",
        "Google AI and ML capabilities",
        True,
        True,
        "https://console.cloud.google.com/apis/credentials",
        "OpenAI Integration",
    ),
    _ExpectedGroup(
        "Tavily Web Search",
        ["TAVILY_API_KEY"],
        "Tavily AI-powered web search integration",
        "Web search capabilities, image search, news search, and content extraction",
        True,
        True,
        "https://tavily.com/#api",
        None,
    ),
    _ExpectedGroup(
        "Firecrawl Web Scraping",
        ["FIRECRAWL_API_KEY"],
        "Firecrawl web scraping and content extraction service",
        "Advanced web content extraction, URL processing, and page scraping",
        True,
        True,
        "https://www.firecrawl.dev/",
        None,
    ),
    _ExpectedGroup(
        "Llama Index",
        ["LLAMA_INDEX_KEY"],
        "Llama Index for document processing and retrieval",
        "Advanced document indexing, RAG capabilities, and structured data retrieval",
        True,
        True,
        "https://docs.llamaindex.ai/",
        None,
    ),
    _ExpectedGroup(
        "Resend Email Service",
        ["RESEND_API_KEY", "RESEND_AUDIENCE_ID", "EMAIL_UNSUBSCRIBE_SECRET"],
        "Resend email delivery service",
        "Email notifications and communication",
        True,
        True,
        "https://resend.com/docs/api-reference/api-keys",
        None,
    ),
    _ExpectedGroup(
        "Weather Service",
        ["OPENWEATHER_API_KEY"],
        "OpenWeather API for weather data",
        "Weather forecasts and current conditions",
        True,
        True,
        "https://openweathermap.org/api",
        None,
    ),
    _ExpectedGroup(
        "Composio Integration",
        ["COMPOSIO_KEY", "COMPOSIO_WEBHOOK_SECRET"],
        "Composio integration service",
        "Composio platform integration and webhook processing",
        True,
        True,
        "https://docs.composio.dev/",
        None,
    ),
    _ExpectedGroup(
        "E2B Code Execution",
        ["E2B_API_KEY"],
        "E2B secure code execution environment",
        "Code execution and sandboxed environments",
        True,
        True,
        "https://e2b.dev/docs",
        None,
    ),
    _ExpectedGroup(
        "Browser Host",
        ["BROWSER_HOST_URL", "BROWSER_HOST_KEY"],
        "gaia-browser-host (self-hosted Chromium) + Browser-Use agent",
        "Autonomous browser automation (the browser_task tool)",
        False,
        True,
        None,
        None,
    ),
    _ExpectedGroup(
        "Dodo Payments",
        ["DODO_PAYMENTS_API_KEY", "DODO_WEBHOOK_PAYMENTS_SECRET"],
        "Dodo payment processing service",
        "Payment processing and subscription management",
        True,
        True,
        "https://docs.dodopayments.com/",
        None,
    ),
    _ExpectedGroup(
        "Blog Management",
        ["BLOG_BEARER_TOKEN"],
        "Blog content management",
        "Blog creation and management",
        True,
        True,
        None,
        None,
    ),
    _ExpectedGroup(
        "Sentry Monitoring",
        ["SENTRY_DSN"],
        "Sentry error tracking and monitoring",
        "Error reporting and application monitoring",
        True,
        True,
        "https://docs.sentry.io/platforms/python/",
        None,
    ),
    _ExpectedGroup(
        "Posthog Analytics",
        ["POSTHOG_PROJECT_TOKEN", "POSTHOG_HOST"],
        "Posthog analytics and event tracking",
        "User behavior analytics and event tracking",
        False,
        True,
        "https://posthog.com/docs/api",
        None,
    ),
]


def _missing_keys(
    missing: list[tuple[SettingsGroup, list[str]]], group_name: str
) -> list[str] | None:
    for group, keys in missing:
        if group.name == group_name:
            return keys
    return None


def test_predefined_groups_registered_count_and_order() -> None:
    """A dropped, duplicated, or reordered ``register_group`` call changes
    either the count or the name sequence — both are asserted here so either
    kind of mutation is caught even before any per-field check runs."""
    groups = SettingsValidator().groups

    assert len(groups) == len(EXPECTED_GROUPS)
    assert [g.name for g in groups] == [e.name for e in EXPECTED_GROUPS]


@pytest.mark.parametrize("expected", EXPECTED_GROUPS, ids=[e.name for e in EXPECTED_GROUPS])
def test_predefined_group_fields_match_exactly(expected: _ExpectedGroup) -> None:
    """Every field of every registered group, asserted against its exact
    expected value — catches a mutated string literal, a flipped boolean, or
    an altered key list on any single group."""
    groups = {g.name: g for g in SettingsValidator().groups}

    group = groups[expected.name]

    assert group.keys == expected.keys
    assert group.description == expected.description
    assert group.affected_features == expected.affected_features
    assert group.required_in_prod == expected.required_in_prod
    assert group.all_required == expected.all_required
    assert group.docs_url == expected.docs_url
    assert group.alternative_group == expected.alternative_group


def test_a_configured_posthog_is_not_reported_missing() -> None:
    """The group's keys must be the settings attribute names verbatim: a key
    that never matches an attribute leaves the group reported missing however
    the app is configured."""
    settings_obj = SimpleNamespace(**dict.fromkeys(POSTHOG_FIELDS, "set"))

    missing = SettingsValidator().validate_settings(settings_obj)

    assert _missing_keys(missing, POSTHOG_GROUP) is None


def test_an_unconfigured_posthog_reports_every_posthog_setting() -> None:
    missing = SettingsValidator().validate_settings(SimpleNamespace())

    assert set(_missing_keys(missing, POSTHOG_GROUP) or []) == POSTHOG_FIELDS


async def test_missing_posthog_is_not_warned_about_in_production() -> None:
    """Analytics is optional in production — a missing token must not raise a
    CRITICAL on every boot, while a genuinely required group still does."""
    validator = SettingsValidator()
    validator.configure(show_warnings=True, is_production=True)
    validator.validate_settings(SimpleNamespace())

    async with captured_wide_event() as event:
        validator.log_validation_results()

    warned = {warning["group_name"] for warning in event["warnings"]}
    assert POSTHOG_GROUP not in warned
    assert "MongoDB Connection" in warned


async def test_missing_posthog_is_warned_about_outside_production() -> None:
    validator = SettingsValidator()
    validator.configure(show_warnings=True, is_production=False)
    validator.validate_settings(SimpleNamespace())

    async with captured_wide_event() as event:
        validator.log_validation_results()

    posthog_warnings = [w for w in event["warnings"] if w["group_name"] == POSTHOG_GROUP]
    assert [set(w["missing_keys"]) for w in posthog_warnings] == [POSTHOG_FIELDS]
