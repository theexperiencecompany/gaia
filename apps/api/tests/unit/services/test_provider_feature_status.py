"""Per-feature status: which engine each feature runs on, read off the runtime's own chains."""

from unittest.mock import patch

import pytest

from app.config.deployment import BlobStoreKind
from app.config.settings import settings
from app.constants.llm import LLMProviderName
from app.constants.providers import (
    S3_BUCKET_FILE_STORAGE,
    BuiltInEngine,
    CredentialProviderName,
    FeatureSpec,
    ProviderFeature,
)
from app.services.blob_store import S3BlobStore
from app.services.providers.feature_status import (
    FeatureStatus,
    _catalog_engine,
    feature_statuses,
    provider_features,
)
from tests.helpers import InMemoryCredentialStore
from tests.s3_fakes import FakeS3Client

_KEYED_SETTINGS = (
    "TAVILY_API_KEY",
    "EXA_API_KEY",
    "BRAVE_API_KEY",
    "SEARXNG_BASE_URL",
    "FIRECRAWL_API_KEY",
    "E2B_API_KEY",
    "RESEND_API_KEY",
    "COMPOSIO_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "CLOUDINARY_CLOUD_NAME",
    "CLOUDINARY_API_KEY",
    "CLOUDINARY_API_SECRET",
    "OPENWEATHER_API_KEY",
    "LLAMA_INDEX_KEY",
    "GITHUB_TOKEN",
    "OPENROUTER_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)


@pytest.fixture
def store(
    selfhost_credential_store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> InMemoryCredentialStore:
    """Boot a fresh self-host instance: nothing in the environment, nothing stored."""
    for field in _KEYED_SETTINGS:
        monkeypatch.setattr(settings, field, None)
    monkeypatch.setattr(settings, "LOCAL_CODE_SANDBOX", False)
    monkeypatch.setattr(settings, "BLOB_STORE", None)
    return selfhost_credential_store


async def _status(feature: ProviderFeature) -> FeatureStatus:
    return (await feature_statuses())[feature]


async def test_every_feature_reports_a_status(store: InMemoryCredentialStore) -> None:
    assert set(await feature_statuses()) == set(ProviderFeature)


async def test_web_search_works_keyless_on_duckduckgo(store: InMemoryCredentialStore) -> None:
    assert await _status(ProviderFeature.WEB_SEARCH) == FeatureStatus(
        available=True, working=True, in_use=[BuiltInEngine.DUCKDUCKGO]
    )


async def test_web_search_lists_stored_and_env_providers_in_waterfall_order(
    store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.save("exa", api_key="stored-exa")
    store.save("searxng", base_url="http://searxng:8080")
    monkeypatch.setattr(settings, "BRAVE_API_KEY", "env-brave")

    status = await _status(ProviderFeature.WEB_SEARCH)

    assert status.in_use == [
        CredentialProviderName.EXA,
        CredentialProviderName.BRAVE,
        CredentialProviderName.SEARXNG,
        BuiltInEngine.DUCKDUCKGO,
    ]


async def test_page_reading_works_keyless_on_the_built_in_reader(
    store: InMemoryCredentialStore,
) -> None:
    assert (await _status(ProviderFeature.PAGE_READING)).in_use == [BuiltInEngine.PAGE_READER]


async def test_a_firecrawl_key_backs_up_the_built_in_reader(
    store: InMemoryCredentialStore,
) -> None:
    store.save("firecrawl", api_key="stored-firecrawl")

    assert (await _status(ProviderFeature.PAGE_READING)).in_use == [
        BuiltInEngine.PAGE_READER,
        CredentialProviderName.FIRECRAWL,
    ]


async def test_code_running_is_off_without_e2b_or_the_local_sandbox(
    store: InMemoryCredentialStore,
) -> None:
    assert await _status(ProviderFeature.CODE_RUNNING) == FeatureStatus(
        available=True, working=False, in_use=[]
    )


async def test_code_running_uses_the_opted_in_local_sandbox(
    store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "LOCAL_CODE_SANDBOX", True)

    assert (await _status(ProviderFeature.CODE_RUNNING)).in_use == [BuiltInEngine.LOCAL_SANDBOX]


async def test_a_saved_e2b_key_takes_code_running_over_the_local_sandbox(
    store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "LOCAL_CODE_SANDBOX", True)
    store.save("e2b", api_key="stored-e2b")

    assert (await _status(ProviderFeature.CODE_RUNNING)).in_use == [CredentialProviderName.E2B]


async def test_file_storage_defaults_to_local_disk(store: InMemoryCredentialStore) -> None:
    assert (await _status(ProviderFeature.FILE_STORAGE)).in_use == [BuiltInEngine.LOCAL_DISK]


async def test_s3_storage_runs_on_the_configured_bucket_and_the_catalog_names_it(
    store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "BLOB_STORE", BlobStoreKind.S3)
    monkeypatch.setattr(
        "app.services.blob_store.s3_blob_store",
        lambda: S3BlobStore(FakeS3Client("gaia"), "gaia", "http://s3.test"),
    )

    assert (await _status(ProviderFeature.FILE_STORAGE)).in_use == [BuiltInEngine.S3_BUCKET]
    assert provider_features()[ProviderFeature.FILE_STORAGE].built_in == S3_BUCKET_FILE_STORAGE


async def test_cloudinary_storage_is_off_until_its_account_is_complete(
    store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "BLOB_STORE", "cloudinary")
    store.save("cloudinary", api_key="stored-key", account_id="cloud")

    assert not (await _status(ProviderFeature.FILE_STORAGE)).working


async def test_cloudinary_storage_runs_on_a_complete_saved_account(
    store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "BLOB_STORE", "cloudinary")
    store.save("cloudinary", api_key="k", account_id="cloud", api_secret="s")

    assert (await _status(ProviderFeature.FILE_STORAGE)).in_use == [
        CredentialProviderName.CLOUDINARY
    ]


async def test_email_and_integrations_are_off_without_a_key(
    store: InMemoryCredentialStore,
) -> None:
    assert not (await _status(ProviderFeature.EMAIL)).working
    assert not (await _status(ProviderFeature.INTEGRATIONS)).working


async def test_saved_keys_turn_email_and_integrations_on(
    store: InMemoryCredentialStore,
) -> None:
    store.save("resend", api_key="stored-resend")
    store.save("composio", api_key="stored-composio")

    assert (await _status(ProviderFeature.EMAIL)).in_use == [CredentialProviderName.RESEND]
    assert (await _status(ProviderFeature.INTEGRATIONS)).in_use == [CredentialProviderName.COMPOSIO]


async def test_ai_models_follow_the_chat_lane_order(store: InMemoryCredentialStore) -> None:
    routes = [(LLMProviderName.GEMINI, "gemini-model"), (LLMProviderName.OLLAMA, "llama")]
    with patch("app.services.providers.feature_status.chat_routes", return_value=routes):
        status = await _status(ProviderFeature.AI_MODELS)

    assert status.in_use == [CredentialProviderName.GEMINI, CredentialProviderName.OLLAMA]


async def test_ai_models_are_off_with_no_chat_lane(store: InMemoryCredentialStore) -> None:
    with patch("app.services.providers.feature_status.chat_routes", return_value=[]):
        assert not (await _status(ProviderFeature.AI_MODELS)).working


def test_a_keyless_engine_on_a_feature_without_a_built_in_is_a_catalog_bug() -> None:
    spec = FeatureSpec(label="AI models", description="x", built_in=None, providers=())

    with pytest.raises(ValueError) as refused:
        _catalog_engine(spec, "ollama")

    assert str(refused.value) == "AI models has no built-in engine, yet 'ollama' needs no key"


async def test_weather_is_off_without_a_key(store: InMemoryCredentialStore) -> None:
    assert await _status(ProviderFeature.WEATHER) == FeatureStatus(
        available=True, working=False, in_use=[]
    )


async def test_weather_runs_on_a_saved_openweather_key(store: InMemoryCredentialStore) -> None:
    store.save("openweather", api_key="stored-owm")

    assert (await _status(ProviderFeature.WEATHER)).in_use == [CredentialProviderName.OPENWEATHER]


@pytest.mark.parametrize(
    ("feature", "built_in", "provider"),
    [
        (ProviderFeature.SCANNED_DOCUMENTS, BuiltInEngine.LOCAL_PARSER, "llamaparse"),
        (ProviderFeature.SKILL_INSTALLS, BuiltInEngine.PUBLIC_GITHUB, "github"),
    ],
)
async def test_a_saved_key_runs_ahead_of_a_feature_s_built_in(
    store: InMemoryCredentialStore,
    feature: ProviderFeature,
    built_in: BuiltInEngine,
    provider: str,
) -> None:
    store.save(provider, api_key="stored-key")

    assert (await _status(feature)).in_use == [CredentialProviderName(provider), built_in]


@pytest.mark.parametrize("feature", [ProviderFeature.BROWSER, ProviderFeature.VOICE])
async def test_self_host_reports_browser_and_voice_unavailable_whatever_is_set(
    store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch, feature: ProviderFeature
) -> None:
    store.save("openrouter", api_key="stored-or")
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.setattr(settings, name, "set")

    assert await _status(feature) == FeatureStatus(available=False, working=False, in_use=[])


async def test_gaia_cloud_runs_browser_and_voice_on_its_own_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "workos")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "env-or")
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.setattr(settings, name, "set")

    statuses = await feature_statuses()

    assert statuses[ProviderFeature.BROWSER].in_use == [BuiltInEngine.HOSTED_BROWSER]
    assert statuses[ProviderFeature.VOICE].in_use == [BuiltInEngine.HOSTED_VOICE]


@pytest.mark.parametrize("missing", ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"])
async def test_gaia_cloud_voice_needs_every_livekit_setting(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "workos")
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.setattr(settings, name, None if name == missing else "set")

    assert (await _status(ProviderFeature.VOICE)).in_use == []


async def test_gaia_cloud_browser_needs_an_openrouter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "workos")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", None)

    assert (await _status(ProviderFeature.BROWSER)).in_use == []
