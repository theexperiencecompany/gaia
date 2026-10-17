#!/usr/bin/env python3
"""Save one provider credential exactly as the setup wizard does; gaia up runs it after first boot.

A chat provider's credential is stored only after the wizard's live probe accepts it.
The key is read from the GAIA_PROVIDER_API_KEY environment variable, never an
argument, so it stays out of the process list and shell history.

Usage (on the host that runs GAIA)::

    GAIA_PROVIDER_API_KEY=... docker compose -p gaia-selfhost exec -T -e GAIA_PROVIDER_API_KEY \
        gaia-backend python -m app.scripts.save_provider --provider custom \
        --base-url https://gateway.example/v1 --model some-model
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from app.constants.providers import (
    CREDENTIAL_PROVIDERS,
    LLM_PROVIDER_KEYS,
    PRESETS,
    ProviderPreset,
)
from app.schemas.providers import ProviderCredentialBody
from app.services.providers.provider_credentials_service import upsert
from app.services.providers.provider_probe_service import probe_provider
from app.services.providers.provider_setup_service import merge_provider_credential
from app.utils.errors import AppError

API_KEY_ENV = "GAIA_PROVIDER_API_KEY"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=CREDENTIAL_PROVIDERS)
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    return parser


async def run(argv: list[str]) -> int:
    """Save the provider argv names and return the process exit code."""
    args = _parser().parse_args(argv)
    preset: ProviderPreset = PRESETS[args.provider]
    try:
        config = await merge_provider_credential(
            args.provider,
            ProviderCredentialBody(
                api_key=os.environ.get(API_KEY_ENV) or None,
                # The endpoint the provider's setup card prefills, e.g. Ollama on the host.
                base_url=args.base_url or preset["base_url"] or None,
                model=args.model,
            ),
        )
        if args.provider in LLM_PROVIDER_KEYS:
            ok, detail, _ = await probe_provider(
                args.provider,
                api_key=config.api_key,
                base_url=config.base_url,
                model=config.model,
            )
            if not ok:
                print(f"Could not save {args.provider}: {detail}", file=sys.stderr)
                return 1
        await upsert(args.provider, config)
    except AppError as e:
        print(f"Could not save {args.provider}: {e.message}", file=sys.stderr)
        return 1
    print(f"Saved {args.provider}. Change it any time in Settings → Providers & Tools.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
