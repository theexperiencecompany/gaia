"""Service classes must be stateless — module functions or @staticmethod-only.

``apps/api/CLAUDE.md`` -> "Service Layer": services are async module-level
functions. If grouping is wanted, use a class with ``@staticmethod`` methods
only — never ``self``. A ``*Service`` class that carries instance state and
methods is the anti-pattern (a hidden singleton with injected dependencies).

Scope is deliberately the ``*Service`` naming convention, not every class in
``app/services/``: connection pools, registries, watchers, stores and client
wrappers legitimately hold state and are not named ``*Service``. Classes whose
base is a data/enum/exception/protocol/ABC type are skipped — a ``*Service`` ABC
is a polymorphic base, and Pydantic/enum lookalikes are not services.

The ``ALLOWLIST`` grandfathers the stateful services that predate the lint. It
is a ratchet — remove an entry when the class is converted, never add one.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import Violation

RULE = "no-service-classes"
WHY = "a *Service class with instance state is a hidden singleton; services should be module functions or @staticmethod-only"
DOC = "tools/lints/README.md#no-service-classes"

# Base classes that make a *Service-named class NOT a stateful service:
# data models, enums, exceptions, protocols, and abstract polymorphic bases.
_ALLOWED_BASE_NAMES = frozenset(
    {
        "BaseModel",
        "Enum",
        "StrEnum",
        "IntEnum",
        "IntFlag",
        "TypedDict",
        "Protocol",
        "ABC",
        "ABCMeta",
        "Exception",
        "BaseException",
        "AppError",
    }
)

# Ratchet allowlist of stateful *Service classes that predate the lint. Remove an
# entry when the class is converted to module functions; never add one.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # Documented in-memory singleton (see apps/api/CLAUDE.md Database table).
        "ComposioService",
        # Wraps the authenticated Dodo Payments SDK client (holds SDK state).
        "DodoPaymentService",
        # Holds the webhook verifier + per-event handler registry.
        "PaymentWebhookService",
        # Holds channel-adapter + action-handler registries.
        "NotificationService",
        # Legacy DI shape (mongodb passed in) — convertible follow-up.
        "DeviceTokenService",
        # Holds a Chroma collection name — thin state, convertible follow-up.
        "GaiaKnowledgeService",
    }
)


def _base_names(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in cls.bases:
        node = base.value if isinstance(base, ast.Subscript) else base
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _instance_methods(cls: ast.ClassDef) -> list[str]:
    """Methods whose first arg is ``self`` and which are not static/class methods."""
    found: list[str] = []
    for item in cls.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        deco_names = {
            (d.func if isinstance(d, ast.Call) else d).id
            for d in item.decorator_list
            if isinstance((d.func if isinstance(d, ast.Call) else d), ast.Name)
        }
        if deco_names & {"staticmethod", "classmethod"}:
            continue
        # posonlyargs first: `def method(self, /)` stores self there, not in args.
        parameters = [*item.args.posonlyargs, *item.args.args]
        if parameters and parameters[0].arg == "self":
            found.append(item.name)
    return found


def check(files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in files:
        if "/app/services/" not in path.as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Service"):
                continue
            if _base_names(node) & _ALLOWED_BASE_NAMES:
                continue
            if node.name in ALLOWLIST:
                continue
            methods = _instance_methods(node)
            if not methods:
                continue
            violations.append(
                Violation(
                    path=path,
                    line=node.lineno,
                    detail=f"service class '{node.name}' has instance methods ({', '.join(methods[:4])})",
                    fix=(
                        f"convert '{node.name}' to module-level async functions, or make "
                        "its methods @staticmethod (no self) — see the Service Layer rule"
                    ),
                )
            )
    return violations
