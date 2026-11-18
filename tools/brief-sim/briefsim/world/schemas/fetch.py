"""Refresh the vendored Composio tool definitions the fake world serves.

  COMPOSIO_KEY=... python -m briefsim.world.schemas.fetch

Reads Composio's public tool catalog (no user data) for exactly the slugs the
fake apps implement and writes one JSON file per toolkit beside this module.
"""

import json
import os
from pathlib import Path
import subprocess

from briefsim.world.apps import SIMULATED_SLUGS
import httpx

COMPOSIO_API = "https://backend.composio.dev/api/v3.1/tools"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]


def main() -> None:
    key = os.environ["COMPOSIO_KEY"]
    with httpx.Client(headers={"x-api-key": key}, timeout=60) as client:
        for toolkit, slugs in SIMULATED_SLUGS.items():
            response = client.get(
                COMPOSIO_API,
                params={"toolkit_slug": toolkit, "tool_slugs": ",".join(slugs), "limit": 100},
            )
            response.raise_for_status()
            items = response.json()["items"]
            missing = set(slugs) - {item["slug"] for item in items}
            if missing:
                raise SystemExit(f"{toolkit}: Composio no longer lists {sorted(missing)}")
            out = HERE / f"{toolkit.lower()}.json"
            out.write_text(json.dumps(sorted(items, key=lambda i: i["slug"]), indent=1) + "\n")
            print(f"{toolkit}: {len(items)} tools -> {out.name}")
    # The repo formats JSON with Biome; write what the commit hook would.
    subprocess.run(
        [str(REPO / "node_modules/.bin/biome"), "format", "--write", str(HERE)], check=True
    )


if __name__ == "__main__":
    main()
