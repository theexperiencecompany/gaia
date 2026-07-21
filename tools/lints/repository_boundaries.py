"""The repository layer is the only path to MongoDB — enforce its boundary.

``app/db/repositories/CLAUDE.md``: services reach Mongo through typed domain
repositories; raw ``ObjectId``, Mongo filters, and dict-shaped documents never
cross that boundary. mypy strictness alone cannot catch a leak (a strict module
can still hand a ``dict[str, Any]`` outward), so this AST rule mechanically holds
three lines:

1. ``app.db.mongodb.collections`` may be imported only inside ``app/db/repositories/``
   and ``app/db/mongodb/`` — everywhere else goes through a repository.
2. ``bson`` / ``ObjectId`` may be imported only inside ``app/db/`` — id-codec is a
   repository-internal concern.
3. Public methods of classes in ``app/db/repositories/`` must be fully annotated
   with no ``Any`` / ``dict[str, Any]`` — the typed boundary is the whole point.
   Underscore-prefixed methods (the subclass seam) are exempt.

Checks 1 and 2 carry ratchet ``ALLOWLIST``s of the call sites that predate the
repository layer. Entries are removed as each domain is migrated — never added. A
new violation cannot be allowlisted away; it must be fixed, which is the point.

(A fourth check — no ``get_cache``/``set_cache``/``delete_cache`` outside the
allowed layers — will be armed once the domains no longer cache repository-managed
data by hand.)
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
_BSON_ALLOWED_DIRS = ("db/",)

# Ratchet allowlist: files importing app.db.mongodb.collections that predate the
# repository layer. Each is removed when its domain is migrated. Never add an entry.
COLLECTIONS_IMPORT_ALLOWLIST: frozenset[str] = frozenset(
    {
        # agents/
        "agents/core/subagents/handoff_tools.py",
        "agents/core/subagents/provider_subagents.py",
        "agents/memory/email_processor.py",
        "agents/skills/registry.py",
        "agents/tools/integration_tool.py",
        # api/
        "api/v1/endpoints/integrations/config.py",
        # NOTE: integrations/public.py stays allowlisted for integrations_collection /
        # user_integrations_collection (Wave F); its workflows aggregation is migrated.
        "api/v1/endpoints/integrations/public.py",
        "api/v1/endpoints/notification.py",
        "api/v1/endpoints/onboarding.py",
        "api/v1/endpoints/user.py",
        # helpers/
        "helpers/agent_helpers.py",
        "helpers/email_helpers.py",
        "helpers/message_helpers.py",
        # memory/
        "memory/consolidation.py",
        # scripts/
        "scripts/backfill_public_workflow_descriptions.py",
        # services/
        "services/dev_service.py",
        "services/device/device_service.py",
        "services/file_service.py",
        "services/integrations/community_service.py",
        "services/integrations/custom_crud.py",
        "services/integrations/integration_resolver.py",
        "services/integrations/marketplace.py",
        "services/integrations/publish_service.py",
        "services/integrations/user_integration_status.py",
        "services/integrations/user_integrations.py",
        "services/mcp/mcp_client.py",
        "services/mcp/mcp_tools_store.py",
        "services/oauth/oauth_service.py",
        # Migrated off users_collection in the users wave; still allowlisted here
        # for their other collections (todos/workflows/conversations), pending
        # those domains' waves.
        "services/onboarding/intelligence_job.py",
        "services/onboarding/intelligence_service.py",
        "services/onboarding/onboarding_service.py",
        "services/onboarding/post_onboarding_service.py",
        "services/onboarding/social_profile_service.py",
        "services/onboarding/writing_style_service.py",
        "services/payments/payment_service.py",
        "services/payments/payment_webhook_service.py",
        "services/provider_metadata_service.py",
        "services/user_service.py",
        "services/voice_service.py",
        "services/workspace_sync.py",
        # utils/
        "utils/agent_utils.py",
        "utils/embedding_utils.py",
        "utils/notification/channel_preferences.py",
        "utils/profile_card.py",
        # workers/
        "workers/tasks/cleanup_tasks.py",
        "workers/tasks/maintenance_sweep_tasks.py",
        "workers/tasks/memory_backfill_tasks.py",
        "workers/tasks/onboarding_tasks.py",
        "workers/tasks/user_tasks.py",
    }
)

# Ratchet allowlist: files importing bson/ObjectId that predate the repository
# layer. Removed when the domain migrates its id-codec into its repository.
BSON_IMPORT_ALLOWLIST: frozenset[str] = frozenset(
    {
        # agents/
        "agents/memory/email_processor.py",
        # api/
        "api/v1/endpoints/integrations/config.py",
        "api/v1/endpoints/notification.py",
        "api/v1/endpoints/onboarding.py",
        "api/v1/endpoints/user.py",
        # helpers/
        "helpers/email_helpers.py",
        "helpers/message_helpers.py",
        # memory/
        "memory/consolidation.py",
        # models/
        "models/blog_models.py",
        # services/
        "services/integrations/marketplace.py",
        "services/integrations/user_integrations.py",
        "services/oauth/oauth_service.py",
        "services/onboarding/post_onboarding_service.py",
        "services/onboarding/social_profile_service.py",
        "services/onboarding/writing_style_service.py",
        "services/payments/payment_service.py",
        "services/payments/payment_webhook_service.py",
        "services/provider_metadata_service.py",
        "services/user_service.py",
        "services/voice_service.py",
        # utils/
        "utils/embedding_utils.py",
        "utils/notification/channel_preferences.py",
        "utils/profile_card.py",
        # workers/
        "workers/tasks/maintenance_sweep_tasks.py",
        "workers/tasks/memory_backfill_tasks.py",
        "workers/tasks/onboarding_tasks.py",
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

    return violations
