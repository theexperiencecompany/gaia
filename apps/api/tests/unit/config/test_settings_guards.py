"""Production boot-guards and the OpenRouter base-URL passthrough.

The dev-only overrides (`DEV_AUTH_BYPASS_EMAIL`, `OPENROUTER_BASE_URL`) must make
`get_settings()` refuse to start under `ENV=production`, and `init_openrouter_llm`
must forward the base-URL override only in development.
"""

from types import SimpleNamespace

from pydantic import ValidationError
import pytest


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    from app.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# Every var the production guard rejects. The list must stay complete: the
# tests below clear it so only the override under test is present, and a
# missing entry lets a developer's ambient .env fire an earlier guard and
# fail the wrong assertion (DEV_UNLIMITED_RATE_LIMITS did exactly that).
DEV_OVERRIDE_VARS = (
    "DEV_AUTH_BYPASS_EMAIL",
    "DEV_UNLIMITED_RATE_LIMITS",
    "OPENROUTER_BASE_URL",
    "GAIA_SIM_MODE",
)


def _fake_chat_openrouter(captured: dict[str, object]) -> type:
    """A ChatOpenRouter double that records its construction kwargs.

    It carries a ``client.sdk_configuration`` because the real class does and
    ``without_sdk_retry`` writes the SDK's retry config there — a double missing
    it would pass while the production path raises.
    """

    class _FakeChatOpenRouter:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.client = SimpleNamespace(sdk_configuration=SimpleNamespace(retry_config=None))

        def configurable_fields(self, **_: object) -> "_FakeChatOpenRouter":
            return self

    return _FakeChatOpenRouter


@pytest.mark.parametrize(
    ("env_var", "value"),
    [
        ("DEV_AUTH_BYPASS_EMAIL", "dev@gaia.local"),
        ("OPENROUTER_BASE_URL", "http://localhost:9797"),
        ("GAIA_SIM_MODE", "1"),
    ],
)
def test_dev_overrides_block_production_boot(monkeypatch, env_var, value):
    from app.config.settings import get_settings

    monkeypatch.setenv("ENV", "production")
    # Isolate from the developer's ambient .env: only the override under test
    # may be present, or an earlier guard fires first and the match fails.
    for var in DEV_OVERRIDE_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(env_var, value)

    with pytest.raises(RuntimeError, match=env_var):
        get_settings()


def test_openrouter_base_url_allowed_in_development(monkeypatch):
    from app.config.settings import get_settings

    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://localhost:9797")

    settings_obj = get_settings()

    assert settings_obj.ENV == "development"
    assert settings_obj.OPENROUTER_BASE_URL == "http://localhost:9797"


def test_init_openrouter_omits_base_url_outside_sim_dev(monkeypatch):
    from app.agents.llm import client

    captured: dict[str, object] = {}

    monkeypatch.setattr(client, "ChatOpenRouter", _fake_chat_openrouter(captured))
    monkeypatch.setattr(client.settings, "ENV", "development")
    monkeypatch.setattr(client.settings, "GAIA_SIM_MODE", False)
    monkeypatch.setattr(client.settings, "OPENROUTER_BASE_URL", "http://localhost:9797")
    monkeypatch.setattr(client.settings, "OPENROUTER_API_KEY", "sk-stub-not-used")

    client.init_openrouter_llm().loader_func()

    # Outside sim mode base_url must not be passed AT ALL — passing None would
    # override ChatOpenRouter's OPENROUTER_API_BASE env default_factory.
    # Redirecting to the stub is sim mode's job (_sim_llm).
    assert "base_url" not in captured


def test_init_openrouter_omits_base_url_in_production(monkeypatch):
    from app.agents.llm import client

    captured: dict[str, object] = {}

    monkeypatch.setattr(client, "ChatOpenRouter", _fake_chat_openrouter(captured))
    monkeypatch.setattr(client.settings, "ENV", "production")
    monkeypatch.setattr(client.settings, "GAIA_SIM_MODE", False)
    # Even if the override leaks into a production settings object, it is ignored.
    monkeypatch.setattr(
        client.settings, "OPENROUTER_BASE_URL", "http://localhost:9797", raising=False
    )
    monkeypatch.setattr(client.settings, "OPENROUTER_API_KEY", "sk-real")

    client.init_openrouter_llm().loader_func()

    # Production construction is identical to pre-sim behavior: no base_url
    # kwarg, so ChatOpenRouter's own OPENROUTER_API_BASE env default applies.
    assert "base_url" not in captured


def test_dev_override_fields_exist_on_all_settings_classes():
    """client.py reads GAIA_SIM_MODE in decorator args at import time — the
    fields must exist on EVERY settings class or production boot crashes with
    AttributeError before any provider initializes (regression: they were once
    declared only on DevelopmentSettings)."""
    from app.config.settings import CommonSettings, DevelopmentSettings, ProductionSettings

    for cls in (CommonSettings, DevelopmentSettings, ProductionSettings):
        assert "GAIA_SIM_MODE" in cls.model_fields, cls.__name__
        assert "OPENROUTER_BASE_URL" in cls.model_fields, cls.__name__


def _prod_settings(**overrides):
    """Build ProductionSettings with all required fields stubbed.

    Direct construction (not get_settings()) so the test exercises only the
    field validators — no ambient .env, no boot guards, no missing-key noise.
    """
    from app.config.settings import ProductionSettings

    dummies: dict[str, object] = {}
    for name, field in ProductionSettings.model_fields.items():
        if not field.is_required():
            continue
        annotation = field.annotation
        if annotation is bool:
            dummies[name] = False
        elif annotation is int:
            dummies[name] = 0
        else:
            dummies[name] = "x"
    dummies.update(overrides)
    return ProductionSettings(_env_file=None, **dummies)


def test_production_rejects_http_dodo_base_url():
    """A plain-http DODO_PAYMENTS_BASE_URL would send the API key in cleartext —
    ProductionSettings must reject it instead of silently accepting it."""
    with pytest.raises(ValidationError, match="must use https"):
        _prod_settings(DODO_PAYMENTS_BASE_URL="http://localhost:8899")


def test_production_allows_https_dodo_base_url():
    settings_obj = _prod_settings(DODO_PAYMENTS_BASE_URL="https://dodo.example.com")

    assert settings_obj.DODO_PAYMENTS_BASE_URL == "https://dodo.example.com"


def test_production_allows_unset_dodo_base_url():
    """Leaving DODO_PAYMENTS_BASE_URL unset stays valid — production uses the
    real Dodo endpoint by default. (None passed explicitly to override any
    ambient env var; the validator's job is to allow the unset case.)"""
    settings_obj = _prod_settings(DODO_PAYMENTS_BASE_URL=None)

    assert settings_obj.DODO_PAYMENTS_BASE_URL is None


def test_development_allows_http_dodo_base_url(monkeypatch):
    """The stub/sandbox override is a dev concern — local mirrors are http."""
    from app.config.settings import get_settings

    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("DODO_PAYMENTS_BASE_URL", "http://localhost:8899")

    settings_obj = get_settings()

    assert settings_obj.DODO_PAYMENTS_BASE_URL == "http://localhost:8899"
