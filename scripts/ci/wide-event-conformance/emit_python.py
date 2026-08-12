"""Emit the contract's scenarios through the REAL Python logging stack.

Nothing here is a fixture: the lines land on stdout via ``shared.py.logging``'s
JSON sink and ``shared.py.wide_events``' boundaries, exactly as a running API,
worker or voice agent produces them. ``run.py`` diffs this output against the
TypeScript emitter's, so a change to either sink shows up here as a shape diff.

Run through ``run.py``; standalone it is
``uv run --project libs python scripts/ci/wide-event-conformance/emit_python.py``.
"""

from __future__ import annotations

import asyncio
import os

# The sink reads these at import time, so they must be set before the first
# `shared.py` import. Fixed values keep the emitted lines byte-comparable
# between runs and between machines.
os.environ["LOG_FORMAT"] = "json"
os.environ["LOG_LEVEL"] = "DEBUG"
os.environ.setdefault("ENV", "development")
os.environ.setdefault("GAIA_SERVICE_NAME", "gaia-backend")

from shared.py.wide_events import log, wide_task


def _emit_realtime_scenarios() -> None:
    """Scenarios 1-5: real-time lines, deliberately outside any boundary."""
    log.info("conformance_info", op_index=1)
    log.warning("conformance_warning", error_type="SlowResponse")
    upstream = ConnectionError("upstream refused")
    log.error(
        "conformance_error",
        http_status=502,
        error_type=type(upstream).__name__,
        error=str(upstream),
    )
    log.audit("conformance_audit", actor="u_1")
    # App code fighting the envelope: both keys must come back as ctx_<key>
    # with the line's real service/level intact.
    log.error("conformance_collision", service="HIJACKED", level="HIJACKED")


async def _emit_boundary_scenarios() -> None:
    """Scenarios 6-7: the canonical event, on the success and failure paths."""
    async with wide_task("conformance_success", platform="cli"):
        log.set(operation="demo", component="conformance")
        # Two writes of one namespace, with disjoint keys: both runtimes must
        # ACCUMULATE them. A replacing `set` drops trigger_type here, which is
        # exactly the production bug this scenario exists to pin.
        log.set(workflow={"id": "wf_1", "trigger_type": "schedule"})
        log.set(workflow={"status": "success"})
        log.warning("conformance_warning", error_type="SlowResponse")
        log.error(
            "conformance_error",
            http_status=502,
            error_type="ConnectionError",
            error="upstream refused",
        )
        log.audit("conformance_audit", actor="u_1")

    try:
        async with wide_task("conformance_failure", platform="cli"):
            raise RuntimeError("boom {not a format string}")
    except RuntimeError:
        pass


async def main() -> None:
    """Emit every contract scenario in order."""
    _emit_realtime_scenarios()
    await _emit_boundary_scenarios()
    # Loguru's json sink runs with enqueue=True (a writer thread); without this
    # the process can exit with lines still queued and the runner sees a short,
    # confusingly "missing scenario" capture instead of a shape diff.
    await asyncio.sleep(0.2)


if __name__ == "__main__":
    asyncio.run(main())
