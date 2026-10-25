"""Transport for the JEV Decisions API, shared by every HIL question asked of it.

One POST per call, validated where received. Failure raises — each caller
decides its own degradation (LLM fallback, ask, leave pending), never this
module.
"""

from collections.abc import Mapping

import httpx

from app.constants.hil import HIL_JEV_MODEL_NAME, HIL_JEV_TIMEOUT_SECONDS, HIL_JEV_URL
from app.constants.providers import CredentialProviderName
from app.models.jev_models import JevDecisionsResponse
from app.services.providers.provider_credentials_service import ProviderConfig, resolve


async def post_decisions(
    state: Mapping[str, object], questions: Mapping[str, Mapping[str, object]]
) -> JevDecisionsResponse:
    """One Decisions call on the saved or env OpenRouter key; raises on a missing key, transport failure, or a malformed body."""
    config: ProviderConfig | None = await resolve(CredentialProviderName.OPENROUTER)
    key = config.api_key if config else None
    if not key:
        raise RuntimeError("No OpenRouter key saved or set; cannot reach the JEV judge")
    async with httpx.AsyncClient(timeout=HIL_JEV_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            HIL_JEV_URL,
            json={"model": HIL_JEV_MODEL_NAME, "state": state, "questions": questions},
            headers={"Authorization": f"Bearer {key}"},
        )
        resp.raise_for_status()
        return JevDecisionsResponse.model_validate(resp.json())
