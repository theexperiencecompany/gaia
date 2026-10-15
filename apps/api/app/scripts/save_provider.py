#!/usr/bin/env python3
"""Save one provider credential exactly as the setup wizard does; gaia up runs it after first boot.

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

from app.constants.providers import CREDENTIAL_PROVIDERS, PRESETS
from app.services.providers.provider_setup_service import save_provider_credential
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
    try:
        await save_provider_credential(
            args.provider,
            api_key=os.environ.get(API_KEY_ENV) or None,
            # The endpoint the provider's setup card prefills, e.g. Ollama on the host.
            base_url=args.base_url or PRESETS[args.provider]["base_url"] or None,
            model=args.model,
        )
    except AppError as e:
        print(f"Could not save {args.provider}: {e.message}", file=sys.stderr)
        return 1
    print(f"Saved {args.provider}. Change it any time in Settings → Providers & Tools.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
