"""Auto-inject GAIA's stealth init script on every page Browser-Use drives.

`Page.addScriptToEvaluateOnNewDocument` is scoped to the CDP session that
registers it, so a one-shot call after `browser.start()` only covers the first
tab — a `window.open`/target-created second tab drives fingerprint-naked. The
runner used to poke `browser._cdp_add_init_script(...)` for exactly that first
page; this hooks Browser-Use's own per-target session accessor instead, so the
script rides every target (initial page and any new tab) automatically, through
the library's own mechanism rather than a private call from the runner.

`get_or_create_cdp_session` is the single funnel Browser-Use routes every page
interaction through, so injecting there — once per target, tracked so a repeat
call doesn't stack duplicate scripts — covers the whole session. Browser-Use's
agent driving path uses one-shot `Runtime.evaluate` (never persistent
`Runtime.enable`), so the classic rebrowser `Runtime.enable` leak isn't present
in 0.11.13's main path — nothing to patch there.

Pinned to browser-use==0.11.13; the import fails loudly if the private accessor
or `CDPSession` shape moves.
"""

from browser_use.browser.session import BrowserSession, CDPSession

from app.browser_host.stealth import build_stealth_script
from app.services.browser.fingerprint import current_fingerprint_seed
from shared.py.wide_events import log

_original_get_or_create_cdp_session = BrowserSession.get_or_create_cdp_session
_INJECTED_ATTR = "_gaia_stealth_target_ids"


async def _get_or_create_cdp_session(
    self: BrowserSession, target_id: str | None = None, focus: bool = True
) -> CDPSession:
    """Wrap Browser-Use's per-target session accessor to inject stealth once per target."""
    cdp_session = await _original_get_or_create_cdp_session(self, target_id=target_id, focus=focus)

    injected: set[str] | None = getattr(self, _INJECTED_ATTR, None)
    if injected is None:
        injected = set()
        setattr(self, _INJECTED_ATTR, injected)

    if cdp_session.target_id not in injected:
        injected.add(cdp_session.target_id)
        try:
            await cdp_session.cdp_client.send.Page.addScriptToEvaluateOnNewDocument(
                params={
                    "source": build_stealth_script(current_fingerprint_seed()),
                    "runImmediately": True,
                },
                session_id=cdp_session.session_id,
            )
        except Exception as exc:
            injected.discard(cdp_session.target_id)
            log.warning(
                "browser stealth init-script injection failed",
                error_type=type(exc).__name__,
                target_id=cdp_session.target_id,
            )

    return cdp_session


def apply() -> None:
    """Route every per-target CDP session through the stealth-injecting wrapper."""
    # Deliberate monkeypatch. A plain assignment trips mypy's method-assign and
    # setattr() with a literal name trips ruff B010; the type's own __setattr__ is
    # the honest rebind that satisfies both without an ignore.
    type.__setattr__(BrowserSession, "get_or_create_cdp_session", _get_or_create_cdp_session)


apply()
