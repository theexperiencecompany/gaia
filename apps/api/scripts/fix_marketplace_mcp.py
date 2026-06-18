"""Repair marketplace MCP integrations that were seeded with bad data.

Production-safe data migration. Dry-run by default; pass ``--apply`` to write.
Runs against whatever MongoDB the loaded environment points to, so to fix
production run it with the prod env/Infisical loaded.

Two phases:

1. URL fixes (curated) — repoint integrations whose ``server_url`` is not a
   working MCP endpoint:
     * Smithery *web listing page* (``smithery.ai/server/<name>``) -> MCP host
       (``server.smithery.ai/<name>``);
     * missing ``/mcp`` path (PayPal);
     * upstream moved/removed -> a verified live replacement, optionally with a
       better title/description/icon when the replacement is a different server.
   Dead integrations with no replacement are unpublished (``is_public=False``).

2. Auth reconcile (probe-driven) — for every public custom MCP, detect the real
   auth requirement from the server and reconcile ``requires_auth`` /
   ``auth_type`` to it:
     * 2xx JSON/SSE                       -> none   (requires_auth=False)
     * 401 with WWW-Authenticate / PRM    -> oauth  (RFC 9728 OAuth flow)
     * 401 with no WWW-Authenticate       -> bearer (user supplies an API key)
   Unreachable / ambiguous probes are skipped, never written — a transient
   failure can't flip a healthy server to "no auth".

Every URL replacement is probed before it is written. The probe here is the
same classification the connect flow uses, so the stored config matches what a
real connection attempt will detect.

Verified against the live servers + the prod marketplace on 2026-06-18.

Run from repo root:
    cd apps/api && uv run python scripts/fix_marketplace_mcp.py
    cd apps/api && uv run python scripts/fix_marketplace_mcp.py --apply
"""

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import integrations_collection  # noqa: E402
from app.utils.mcp_oauth_utils import (  # noqa: E402
    _ACCEPT_JSON_SSE,
    _CONTENT_TYPE_JSON,
    _MCP_INITIALIZE_PROBE_REQUEST,
    MCP_PROTOCOL_VERSION,
    OAUTH_PROBE_TIMEOUT,
)


@dataclass(frozen=True)
class Replacement:
    """A curated URL fix. name/description/icon_url are set only for server
    swaps where the new server differs from what the stored metadata describes.
    """

    url: str
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None


# MongoDB dotted path to a custom integration's MCP endpoint URL.
SERVER_URL_FIELD = "mcp_config.server_url"


def _favicon(domain: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"


# current (broken) server_url -> curated replacement.
REPLACEMENTS: dict[str, Replacement] = {
    # Smithery web listing page -> MCP host (same server, needs Smithery key).
    "https://smithery.ai/server/@ScrapeGraphAI/scrapegraph-mcp": Replacement(
        "https://server.smithery.ai/@ScrapeGraphAI/scrapegraph-mcp"
    ),
    "https://smithery.ai/server/@TitanSneaker/paper-search-mcp-openai-v2": Replacement(
        "https://server.smithery.ai/@TitanSneaker/paper-search-mcp-openai-v2"
    ),
    "https://smithery.ai/server/@hamid-vakilzadeh/mcpsemanticscholar": Replacement(
        "https://server.smithery.ai/@hamid-vakilzadeh/mcpsemanticscholar"
    ),
    # Missing /mcp path on the PayPal MCP host (same service).
    "https://mcp.paypal.com": Replacement("https://mcp.paypal.com/mcp"),
    # Upstream Smithery server gone -> live standalone arXiv MCP (same service).
    "https://smithery.ai/server/@lecigarevolant/arxiv-mcp-server-gpt": Replacement(
        "https://arxiv.run.tools/mcp"
    ),
    # Old Smithery qualified name removed -> Smithery's current Google Scholar
    # (same service; existing icon/name/description still accurate).
    "https://server.smithery.ai/@mochow13/google-scholar-mcp": Replacement(
        "https://server.smithery.ai/google/scholar/mcp"
    ),
    # Dead servers -> closest live equivalents (different server: refresh title,
    # description, and icon so the listing matches what it now connects to).
    "https://server.smithery.ai/@smithery-ai/fetch": Replacement(
        url="https://server.smithery.ai/intake-triage/steadyfetch/mcp",
        name="Web Fetch",
        description=(
            "Fetch any web page as clean, LLM-ready markdown or raw HTML, with "
            "built-in retries, caching, and anti-bot handling."
        ),
        icon_url=_favicon("smithery.ai"),
    ),
    "https://server.smithery.ai/@tfscharff/doi-mcp": Replacement(
        url="https://server.smithery.ai/cyanheads/openalex-mcp-server/mcp",
        name="OpenAlex",
        description=(
            "Search the OpenAlex catalog of 270M+ scholarly works — resolve DOIs "
            "to metadata, authors, citations, and references."
        ),
        icon_url=_favicon("openalex.org"),
    ),
    "https://server.smithery.ai/@Aman-Amith-Shastry/scientific_computation": Replacement(
        url="https://server.smithery.ai/wolframmcp/Wolfram/mcp",
        name="Wolfram",
        description=(
            "Rigorous computational intelligence via Wolfram — solve math, linear "
            "algebra, and calculus, handle units, and query curated scientific data."
        ),
        icon_url=_favicon("wolframalpha.com"),
    ),
}

# current (broken) server_url -> unpublished from the marketplace (dead upstream,
# no working remote replacement available).
URL_REMOVALS: set[str] = {
    "https://smithery.ai/server/@Parc-Dev/task-breakdown-server",
}

# Map a probe verdict to the (requires_auth, auth_type) we store.
_AUTH_FIELDS: dict[str, tuple[bool, str | None]] = {
    "none": (False, None),
    "oauth": (True, "oauth"),
    "bearer": (True, "bearer"),
}


async def classify(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    """Classify a URL via a live MCP ``initialize`` POST.

    Returns (verdict, note). verdict is one of:
      none / oauth / bearer  -> reachable, confident auth verdict
      broken                 -> reachable but not an MCP endpoint (redirect/404/HTML)
      unknown                -> probe failed (network/timeout); caller must skip
    """
    if not url:
        return "broken", "no url"
    headers = {
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Accept": _ACCEPT_JSON_SSE,
        "Content-Type": _CONTENT_TYPE_JSON,
    }
    try:
        async with client.stream(
            "POST",
            url,
            json=_MCP_INITIALIZE_PROBE_REQUEST,
            headers=headers,
            timeout=OAUTH_PROBE_TIMEOUT,
            follow_redirects=False,
        ) as resp:
            code = resp.status_code
            ct = resp.headers.get("content-type", "").lower()
            www_auth = resp.headers.get("www-authenticate", "")
            location = resp.headers.get("location", "")
    except httpx.HTTPError as e:
        return "unknown", f"network: {type(e).__name__}"

    if code == 401:
        # RFC 9728: a WWW-Authenticate (esp. with resource_metadata) means the
        # server drives an OAuth flow; a bare 401 means a user-supplied API key.
        if www_auth.strip():
            return "oauth", "401 PRM" if "resource_metadata" in www_auth else "401 bearer-hdr"
        return "bearer", "401 no-www-auth"
    if code < 300 and ("json" in ct or "event-stream" in ct):
        return "none", f"{code} {ct.split(';')[0]}"
    if 300 <= code < 400:
        return "broken", f"{code} redirect -> {location}"
    return "broken", f"{code} {ct.split(';')[0] or 'no-ct'}"


async def phase_url_fixes(client: httpx.AsyncClient, apply: bool) -> tuple[int, int, int]:
    """Apply curated URL replacements and removals. Returns (updated, skipped, removed)."""
    print("== Phase 1: URL fixes ==")
    updated = skipped = removed = 0

    for old_url, repl in REPLACEMENTS.items():
        docs = await integrations_collection.find(
            {SERVER_URL_FIELD: old_url}, {"name": 1, "_id": 0}
        ).to_list(None)
        if not docs:
            continue
        names = ", ".join(d["name"] for d in docs)
        verdict, note = await classify(client, repl.url)
        print(f"• {names}\n    {old_url}\n    -> {repl.url}\n    verdict: {verdict} ({note})")

        if verdict not in _AUTH_FIELDS:
            print("    -> SKIP: replacement not reachable; leaving record untouched.\n")
            skipped += len(docs)
            continue

        requires_auth, auth_type = _AUTH_FIELDS[verdict]
        update: dict[str, object] = {
            SERVER_URL_FIELD: repl.url,
            "mcp_config.requires_auth": requires_auth,
            "mcp_config.auth_type": auth_type,
        }
        if repl.name:
            update["name"] = repl.name
        if repl.description:
            update["description"] = repl.description
        if repl.icon_url:
            update["icon_url"] = repl.icon_url
        extras = [k for k in ("name", "description", "icon_url") if k in update]
        if extras:
            print(f"    also updating: {', '.join(extras)}")

        if apply:
            await integrations_collection.update_many({SERVER_URL_FIELD: old_url}, {"$set": update})
            print("    -> UPDATED\n")
        else:
            print("    -> would update (dry-run)\n")
        updated += len(docs)

    for old_url in URL_REMOVALS:
        docs = await integrations_collection.find(
            {SERVER_URL_FIELD: old_url, "is_public": True}, {"name": 1, "_id": 0}
        ).to_list(None)
        if not docs:
            continue
        names = ", ".join(d["name"] for d in docs)
        print(f"• {names}  (dead upstream)\n    {old_url}")
        if apply:
            await integrations_collection.update_many(
                {SERVER_URL_FIELD: old_url}, {"$set": {"is_public": False}}
            )
            print("    -> UNPUBLISHED\n")
        else:
            print("    -> would unpublish (dry-run)\n")
        removed += len(docs)

    return updated, skipped, removed


def _stored_verdict(mcp_config: dict) -> str:
    """Normalise a stored config to a verdict string for comparison."""
    if not mcp_config.get("requires_auth"):
        return "none"
    return mcp_config.get("auth_type") or "oauth"


async def phase_auth_reconcile(client: httpx.AsyncClient, apply: bool) -> tuple[int, int]:
    """Reconcile requires_auth/auth_type to the live probe for every public MCP.

    Returns (fixed, skipped). Only confident verdicts are written; broken or
    unreachable probes are skipped so a transient failure never rewrites auth.
    """
    print("== Phase 2: Auth reconcile ==")
    docs = await integrations_collection.find(
        {"source": "custom", "is_public": True, SERVER_URL_FIELD: {"$exists": True}},
        {"integration_id": 1, "name": 1, "mcp_config": 1, "_id": 0},
    ).to_list(None)

    fixed = skipped = 0
    for doc in docs:
        mcp_config = doc["mcp_config"]
        url = mcp_config.get("server_url")
        verdict, note = await classify(client, url)
        if verdict not in _AUTH_FIELDS:
            skipped += 1
            continue

        stored = _stored_verdict(mcp_config)
        if stored == verdict:
            continue

        requires_auth, auth_type = _AUTH_FIELDS[verdict]
        print(f"• {doc['name']}: {stored} -> {verdict} ({note})\n    {url}")
        if apply:
            await integrations_collection.update_one(
                {"integration_id": doc["integration_id"]},
                {
                    "$set": {
                        "mcp_config.requires_auth": requires_auth,
                        "mcp_config.auth_type": auth_type,
                    }
                },
            )
            print("    -> UPDATED\n")
        else:
            print("    -> would update (dry-run)\n")
        fixed += 1

    if not fixed:
        print("(no auth mismatches)\n")
    return fixed, skipped


async def run(apply: bool) -> None:
    async with httpx.AsyncClient() as client:
        updated, skipped, removed = await phase_url_fixes(client, apply)
        fixed, auth_skipped = await phase_auth_reconcile(client, apply)

    verb = "Applied" if apply else "Dry-run"
    print(
        f"{verb} — URL fixes: {updated} (skipped {skipped}), unpublished: {removed}, "
        f"auth reconciled: {fixed} (probe-skipped {auth_skipped})"
    )
    if not apply:
        print("\nDry-run only. Re-run with --apply to write these changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write the changes (default: dry-run)."
    )
    args = parser.parse_args()
    asyncio.run(run(args.apply))
