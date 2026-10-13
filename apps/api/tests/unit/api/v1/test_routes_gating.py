"""Router-mount gating: the v1 API surface must not carry self-host routers.

Under AUTH_MODE workos (hosted and dev default) the auth_local signup and
login endpoints must be absent from the assembled v1 router, and the setup
router must be absent too: a hosted deployment exposes neither a
password-registration surface nor an instance-posture probe.
"""

import importlib
from typing import Any


def _collect_paths(router: Any, prefix: str = "") -> list[str]:
    """Flatten a router tree into effective route paths.

    Recent FastAPI wraps include_router calls in lazy included-router nodes
    instead of copying routes onto the parent; walk those recursively and
    re-apply each include prefix.
    """
    paths: list[str] = []
    for item in router.routes:
        original = getattr(item, "original_router", None)
        if original is not None:
            include_prefix = getattr(item.include_context, "prefix", "") or ""
            paths.extend(_collect_paths(original, prefix + include_prefix))
        elif getattr(item, "path", None):
            paths.append(prefix + item.path)
    return paths


def _mounted_paths() -> set[str]:
    """Reload the v1 routes module and return every mounted route path.

    A full reload re-runs the module body, so conditional mounts are
    re-evaluated against the settings singleton as it stands right now.
    """
    import app.api.v1.routes as routes_module

    importlib.reload(routes_module)
    return set(_collect_paths(routes_module.router))


def test_workos_mode_mounts_no_auth_local_routes(monkeypatch):
    """The production/auth-default mode must never include auth_local."""
    from app.config.settings import settings

    original_mode = settings.AUTH_MODE
    try:
        monkeypatch.setattr(settings, "AUTH_MODE", "workos")
        paths = _mounted_paths()
    finally:
        # Rebuild the module under its original mode so later imports see a
        # pristine router (setattr back first, THEN reload).
        monkeypatch.setattr(settings, "AUTH_MODE", original_mode)
        _mounted_paths()

    assert "/auth/signup" not in paths
    assert "/auth/login" not in paths
    # Positive control: the reload actually produced the full mounted surface,
    # so the absences above mean "not mounted", not "empty router".
    assert len(paths) > 100
    # The setup router is equally self-host-only: hosted deployments expose no
    # unauthenticated instance-posture probe and no provider-mutation surface.
    assert "/setup/status" not in paths
    assert "/setup/providers/{provider}" not in paths


def test_local_mode_mounts_auth_and_setup_routes(monkeypatch):
    """Self-host mode must mount both routers; a silent unmount must fail loudly."""
    from app.config.settings import settings

    original_mode = settings.AUTH_MODE
    original_env = settings.ENV
    try:
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        monkeypatch.setattr(settings, "ENV", "selfhost")
        paths = _mounted_paths()
    finally:
        monkeypatch.setattr(settings, "AUTH_MODE", original_mode)
        monkeypatch.setattr(settings, "ENV", original_env)
        _mounted_paths()

    assert "/auth/signup" in paths
    assert "/auth/login" in paths
    assert "/setup/status" in paths


def test_development_with_local_auth_mounts_auth_and_setup_routes(monkeypatch):
    """A contributor running without WorkOS gets signup and the setup surface."""
    from app.config.settings import settings

    original_mode = settings.AUTH_MODE
    original_env = settings.ENV
    try:
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        monkeypatch.setattr(settings, "ENV", "development")
        paths = _mounted_paths()
    finally:
        monkeypatch.setattr(settings, "AUTH_MODE", original_mode)
        monkeypatch.setattr(settings, "ENV", original_env)
        _mounted_paths()

    assert "/auth/signup" in paths
    assert "/setup/status" in paths
    assert "/setup/providers/{provider}" in paths
