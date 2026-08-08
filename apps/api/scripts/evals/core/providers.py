"""Provider catalog: config loading, health checks, rotation, settings pinning."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib

import httpx

from .types import PriceBook, ProviderHealth, ProviderPrice

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.toml"

_DEFAULT_LANE = "custom"


@dataclass
class ProviderConfig:
    """A configured provider lane with its env-backed credentials and budget."""

    name: str
    lane: str
    base_url: str | None
    api_key: str | None
    model: str
    budget_usd: float
    price_in_per_1m: float
    price_out_per_1m: float
    discount_pct: float = 0.0

    def configured(self) -> bool:
        return bool(self.api_key or self.lane == "gemini")


@dataclass
class EvalConfig:
    providers: dict[str, ProviderConfig]
    rotation_order: list[str]
    default_max_usd: float
    judge: dict[str, str]


def _env_or_empty(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value
    return ""


def _load_app_env() -> None:
    """Seed process env from apps/api/.env (provider keys live there)."""
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_config(path: Path = CONFIG_PATH) -> EvalConfig:
    _load_app_env()
    with path.open("rb") as f:
        raw = tomllib.load(f)

    providers: dict[str, ProviderConfig] = {}
    for name, p in raw["providers"].items():
        base = _env_or_empty(p.get("base_url_env", ""), "DEV_LLM_BASE_URL")
        key = _env_or_empty(p.get("api_key_env", ""))
        model = _env_or_empty(p.get("model_env", ""))
        if not model:
            model = "deepseek-v4-flash"
        providers[name] = ProviderConfig(
            name=name,
            lane=p.get("lane", _DEFAULT_LANE),
            base_url=base or None,
            api_key=key or None,
            model=model,
            budget_usd=float(p.get("budget_usd", 0.0)),
            price_in_per_1m=float(p.get("price_in_per_1m", 0.0)),
            price_out_per_1m=float(p.get("price_out_per_1m", 0.0)),
            discount_pct=float(p.get("discount_pct", 0.0)),
        )

    return EvalConfig(
        providers=providers,
        rotation_order=list(raw["rotation"]["order"]),
        default_max_usd=float(raw["cost"].get("default_max_usd", 8.0)),
        judge=dict(raw["judge"]),
    )


def price_book(cfg: EvalConfig) -> PriceBook:
    """Per-provider pricing, built once from the catalog."""
    return {
        name: ProviderPrice(p.price_in_per_1m, p.price_out_per_1m, p.discount_pct)
        for name, p in cfg.providers.items()
    }


def judge_model(cfg: EvalConfig) -> str:
    """Resolve the judge model id from the configured env var."""
    return _env_or_empty(cfg.judge.get("model_env", "")) or "deepseek-v4-pro"


def health_check(p: ProviderConfig) -> ProviderHealth:
    """Cheap 1-token probe; skips (with reason) when credentials are missing."""
    if not p.configured():
        return ProviderHealth(False, f"no API key for provider '{p.name}' (env missing)")
    if p.lane == "gemini":
        return ProviderHealth(True, "gemini lane verified by key presence only")
    if not p.base_url:
        return ProviderHealth(False, f"provider '{p.name}' has no base URL")
    url = p.base_url.rstrip("/") + "/chat/completions"
    try:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {p.api_key}"},
            json={
                "model": p.model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            },
            timeout=15.0,
        )
    except httpx.HTTPError as e:
        return ProviderHealth(False, f"{p.name} unreachable: {e}")
    if r.status_code == 401:
        return ProviderHealth(False, f"{p.name} rejected the API key (401)")
    if r.status_code in (429, 402):
        return ProviderHealth(False, f"{p.name} quota exhausted ({r.status_code})")
    if r.status_code >= 500:
        return ProviderHealth(False, f"{p.name} server error ({r.status_code})")
    return ProviderHealth(True)


def rotation_chain(cfg: EvalConfig, providers: list[str] | None, exclude: list[str]) -> list[str]:
    """Resolve the effective provider order for a run."""
    excluded = set(exclude)
    if providers:
        order = [p for p in providers if p not in excluded and p in cfg.providers]
    else:
        order = [p for p in cfg.rotation_order if p not in excluded]
    return order


def pin_settings(provider: ProviderConfig) -> None:
    """Pin the app's custom-LLM lane to this provider (in-process runs).

    Mutates the shared settings singleton and resets the lazy provider so the
    next graph build re-initializes against the new base URL/key/model.
    """
    if provider.lane != "custom":
        return
    from app.config.settings import settings
    from app.core.lazy_loader import providers

    settings.DEV_LLM_BASE_URL = provider.base_url
    settings.DEV_LLM_API_KEY = provider.api_key
    settings.DEV_LLM_MODEL = provider.model
    if settings.GAIA_SIM_MODE:
        return
    if providers.is_initialized("custom_llm"):
        providers.reset("custom_llm")
