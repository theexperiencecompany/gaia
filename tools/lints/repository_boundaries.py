"""The repository layer is the only path to MongoDB — enforce its boundary.

``app/db/repositories/CLAUDE.md``: services reach Mongo through typed domain
repositories; raw ``ObjectId``, Mongo filters, and dict-shaped documents never
cross that boundary. mypy strictness alone cannot catch a leak (a strict module
can still hand a ``dict[str, Any]`` outward), so this AST rule mechanically holds
four lines:

1. ``app.db.mongodb.collections`` may be imported only inside ``app/db/repositories/``
   and ``app/db/mongodb/`` — everywhere else goes through a repository.
2. ``bson`` / ``ObjectId`` may be imported only inside ``app/db/`` — id-codec is a
   repository-internal concern.
3. Public methods of classes in ``app/db/repositories/`` must be fully annotated
   with no ``Any`` / ``dict[str, Any]`` — the typed boundary is the whole point.
   Underscore-prefixed methods (the subclass seam) are exempt.
4. The entity-cache helpers (``get_cache`` / ``set_cache`` / ``delete_cache`` /
   ``delete_cache_by_pattern`` / ``get_and_delete_cache``) may be imported only
   inside ``app/db/`` (the repository ``CachePolicy`` machinery) and
   ``app/decorators/`` (the ``@Cacheable`` / ``@CacheInvalidator`` machinery) —
   plus a ratchet allowlist of the *non-entity* caches that legitimately cache by
   hand (aggregate rollups, tokens, external-data / derived-display caches). This
   stops a NEW service from hand-caching a repository-managed entity behind the
   repository's back, where it would drift from the entity CachePolicy. The raw
   ``redis_cache`` client (locks / rate-limits) is a different concern, not banned.

Checks 1, 2 and 4 carry ratchet ``ALLOWLIST``s of the call sites that predate the
repository layer. Entries are removed as each domain is migrated — never added. A
new violation cannot be allowlisted away; it must be fixed, which is the point.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import Violation

RULE = "repository-boundaries"
WHY = "services must reach Mongo through typed repositories; raw collections/ObjectId/dict must not cross the boundary"
DOC = "tools/lints/README.md#repository-boundaries"

_COLLECTIONS_MODULE = "app.db.mongodb.collections"

# Directories where each restricted import is legitimately allowed.
_COLLECTIONS_ALLOWED_DIRS = ("db/repositories/", "db/mongodb/")
# scripts/: operational one-shot tooling (run manually against the DB, never on
# a request path) deliberately works on raw documents across every store, so the
# repository boundary does not apply there.
_BSON_ALLOWED_DIRS = ("db/", "scripts/")

# Ratchet allowlist: files importing app.db.mongodb.collections from outside the
# repository layer. Every domain is migrated and the per-collection module
# attributes have been removed, so ``get_async_collection`` is the only thing left
# to import — this allowlist is at its final, legitimate remainder.
# Entries are removed if a script is retired — never added.
COLLECTIONS_IMPORT_ALLOWLIST: frozenset[str] = frozenset(
    {
        # One-shot backfill script that resolves the workflows collection through
        # the supported ``get_async_collection`` accessor; it predates the
        # repository and is run manually, not part of any request path.
        "scripts/backfill_public_workflow_descriptions.py",
    }
)

# Ratchet allowlist: files importing bson/ObjectId that predate the repository
# layer. Removed when the domain migrates its id-codec into its repository.
BSON_IMPORT_ALLOWLIST: frozenset[str] = frozenset(
    {
        # api/
        "api/v1/endpoints/integrations/config.py",
        "api/v1/endpoints/user.py",
        # models/
        "models/blog_models.py",
        # utils/
        "utils/profile_card.py",
    }
)

# The entity-cache helpers that must not be hand-called outside the cache layers.
# (``redis_cache`` — the raw client for locks / rate-limits — is deliberately absent.)
_CACHE_MODULE = "app.db.redis"
_CACHE_FUNCS = frozenset(
    {"get_cache", "set_cache", "delete_cache", "delete_cache_by_pattern", "get_and_delete_cache"}
)
_CACHE_ALLOWED_DIRS = ("db/", "decorators/")

# Ratchet allowlist: the NON-entity caches that legitimately call the cache helpers
# by hand — aggregate rollups, tokens, and external-data / derived-display caches.
# None of these cache a repository-managed entity (those live in the repos'
# CachePolicy). Entries are removed if a cache is retired; new ones are not added —
# a new hand-cache in a service must justify itself, not be allowlisted away.
CACHE_CALL_ALLOWLIST: frozenset[str] = frozenset(
    {
        # agents/ + helpers/ + utils/ — subagent/handoff display metadata (name/icon)
        "agents/core/subagents/handoff_tools.py",
        "helpers/agent_helpers.py",
        "utils/agent_utils.py",
        # external-data / derived caches (web, weather, favicon, research)
        "agents/tools/research_tool.py",
        "utils/favicon_utils.py",
        "utils/internet_utils.py",
        "utils/weather_utils.py",
        # memory retrieval / context / consolidation caches (not entity docs)
        "memory/consolidation.py",
        "memory/context.py",
        "memory/retrieval.py",
        # tokens / auth / short-lived handshake caches
        "core/bot_auth_middleware.py",
        "services/connect_link_service.py",
        "services/mcp/mcp_token_store.py",
        # per-user / derived aggregate caches + their imperative invalidations
        "api/v1/endpoints/todos.py",
        "services/device/device_service.py",
        "services/email_profile_service.py",
        "services/onboarding/inbox_scan_cache.py",
        # marketplace / MCP-tools aggregate rollups + their cache-busts (Decision 2)
        "services/integrations/community_service.py",
        "services/integrations/custom_crud.py",
        "services/integrations/integration_connection_service.py",
        "services/integrations/publish_service.py",
        "services/integrations/user_integrations.py",
        "services/mcp/mcp_client.py",
        "services/mcp/mcp_tools_service.py",
    }
)


def _app_relative(path: Path) -> str | None:
    """Path relative to the ``app/`` package root, e.g. ``services/notes_service.py``."""
    posix = path.as_posix()
    marker = "/app/"
    idx = posix.rfind(marker)
    if idx == -1:
        return posix if posix.startswith("app/") else None
    return posix[idx + len(marker) :]


def _collections_imports(tree: ast.Module) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == _COLLECTIONS_MODULE:
                hits.append((node.lineno, "from app.db.mongodb.collections import ..."))
            elif node.module == "app.db.mongodb" and any(
                a.name == "collections" for a in node.names
            ):
                hits.append((node.lineno, "from app.db.mongodb import collections"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _COLLECTIONS_MODULE:
                    hits.append((node.lineno, "import app.db.mongodb.collections"))
    return hits


def _bson_imports(tree: ast.Module) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "bson":
            hits.append((node.lineno, f"from {node.module} import ..."))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "bson":
                    hits.append((node.lineno, f"import {alias.name}"))
    return hits


def _cache_imports(tree: ast.Module) -> list[tuple[int, str]]:
    """Imports of the banned entity-cache helpers from ``app.db.redis``."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _CACHE_MODULE:
            banned = sorted(a.name for a in node.names if a.name in _CACHE_FUNCS)
            if banned:
                hits.append((node.lineno, f"from app.db.redis import {', '.join(banned)}"))
    return hits


def _annotation_has_any(annotation: ast.expr) -> bool:
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name) and node.id == "Any":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "Any":
            return True
    return False


def _arg_issue(
    line: int, where: str, arg_name: str, annotation: ast.expr | None
) -> list[tuple[int, str, str]]:
    if annotation is None:
        return [
            (
                line,
                f"public method '{where}' arg '{arg_name}' has no type annotation",
                "annotate every public argument — the repository boundary is fully typed",
            )
        ]
    if _annotation_has_any(annotation):
        return [
            (
                line,
                f"public method '{where}' arg '{arg_name}' is typed Any",
                "use the domain's typed model instead of Any/dict[str, Any]",
            )
        ]
    return []


def _signature_violations(tree: ast.Module) -> list[tuple[int, str, str]]:
    """(line, detail, fix) for public repository methods that leak Any or lack annotations."""
    hits: list[tuple[int, str, str]] = []
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        for item in cls.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name.startswith("_"):
                continue  # underscore = internal subclass seam, exempt
            where = f"{cls.name}.{item.name}"
            args = item.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                if arg.arg in ("self", "cls"):
                    continue
                hits.extend(_arg_issue(item.lineno, where, arg.arg, arg.annotation))
            for special in (args.vararg, args.kwarg):
                if special is not None:
                    hits.extend(_arg_issue(item.lineno, where, special.arg, special.annotation))
            if item.returns is None:
                hits.append(
                    (
                        item.lineno,
                        f"public method '{where}' has no return type annotation",
                        "annotate the return type — the repository boundary is fully typed",
                    )
                )
            elif _annotation_has_any(item.returns):
                hits.append(
                    (
                        item.lineno,
                        f"public method '{where}' returns Any",
                        "return a typed document/result model, not Any",
                    )
                )
    return hits


def check(files: list[Path]) -> list[Violation]:
    """Flag repository-boundary violations (imports, signatures, hand-caching) in ``files``."""
    violations: list[Violation] = []
    for path in files:
        app_rel = _app_relative(path)
        if app_rel is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))

        if not any(app_rel.startswith(d) for d in _COLLECTIONS_ALLOWED_DIRS):
            for line, detail in _collections_imports(tree):
                if app_rel in COLLECTIONS_IMPORT_ALLOWLIST:
                    continue
                violations.append(
                    Violation(
                        path=path,
                        line=line,
                        detail=f"imports collections outside the repository layer ({detail})",
                        fix="call the domain repository in app.db.repositories instead of the collection",
                    )
                )

        if not any(app_rel.startswith(d) for d in _BSON_ALLOWED_DIRS):
            for line, detail in _bson_imports(tree):
                if app_rel in BSON_IMPORT_ALLOWLIST:
                    continue
                violations.append(
                    Violation(
                        path=path,
                        line=line,
                        detail=f"imports bson/ObjectId outside app/db/ ({detail})",
                        fix="keep ObjectId conversion inside the repository (ids are str above it)",
                    )
                )

        if app_rel.startswith("db/repositories/"):
            for line, detail, fix in _signature_violations(tree):
                violations.append(Violation(path=path, line=line, detail=detail, fix=fix))

        if not any(app_rel.startswith(d) for d in _CACHE_ALLOWED_DIRS):
            for line, detail in _cache_imports(tree):
                if app_rel in CACHE_CALL_ALLOWLIST:
                    continue
                violations.append(
                    Violation(
                        path=path,
                        line=line,
                        detail=f"hand-calls the entity-cache helpers outside the cache layers ({detail})",
                        fix="cache repository-managed entities via the repository CachePolicy or the "
                        "@Cacheable/@CacheInvalidator decorators, not raw get_cache/set_cache/delete_cache",
                    )
                )

    return violations
