"""Brutal integration tests for per-integration custom instructions.

These exercise the REAL production code end to end:
- the filesystem materializer + the session-bootstrap staleness gate (no mocks),
- the security guard that stops a crafted integration_id from escaping the
  workspace (the path-traversal fix),
- the MongoDB-backed service, the agent tool, and the subagent context block,
  against a faithful in-memory collection double (only the Mongo driver I/O is
  faked; the service/tool logic, query scoping, truncation and routing are real).

A regression in any of those paths must fail one of these tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.agents.core.subagents import subagent_helpers
from app.agents.tools import integration_instructions_tools as tool_mod
from app.agents.workspace.skill_loader import library_hash
from app.models.integration_instructions_models import (
    MAX_INSTRUCTIONS_CHARS,
    InstructionsEditor,
)
from app.services import integration_instructions_service as svc
from app.services.storage.sessions.lifecycle import _materialize_if_stale
from app.services.storage.sessions.skills import materialize_instructions

INSTR_REL = ("integrations", "slack", "agent", "instructions.md")


# --------------------------------------------------------------------------- #
# Faithful in-memory Mongo collection double (boundary only).                  #
# --------------------------------------------------------------------------- #
class _FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs if length is None else self._docs[:length]


def _matches(doc: dict, flt: dict) -> bool:
    for key, cond in flt.items():
        if isinstance(cond, dict) and "$ne" in cond:
            if doc.get(key) == cond["$ne"]:
                return False
        elif doc.get(key) != cond:
            return False
    return True


class FakeCollection:
    """Executes the query semantics the service relies on — not canned values."""

    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def update_one(self, flt: dict, update: dict, upsert: bool = False) -> None:
        for doc in self.docs:
            if _matches(doc, flt):
                doc.update(update.get("$set", {}))
                return
        if upsert:
            new = {k: v for k, v in flt.items() if not isinstance(v, dict)}
            new.update(update.get("$set", {}))
            new["_id"] = f"oid-{len(self.docs)}"
            self.docs.append(new)

    async def find_one(self, flt: dict, projection: Any = None) -> dict | None:
        for doc in self.docs:
            if _matches(doc, flt):
                return dict(doc)
        return None

    def find(self, flt: dict, projection: Any = None) -> _FakeCursor:
        return _FakeCursor([dict(d) for d in self.docs if _matches(d, flt)])


@pytest.fixture
def fake_collection(monkeypatch: pytest.MonkeyPatch) -> FakeCollection:
    # Back the service with an in-memory collection and bypass the Redis cache
    # (an external I/O edge) so the @Cacheable/@CacheInvalidator decorators
    # short-circuit — the service logic, not the cache, is under test here.
    from app.db.redis import redis_cache

    monkeypatch.setattr(redis_cache, "redis", None)
    fake = FakeCollection()
    monkeypatch.setattr(svc, "integration_instructions_collection", fake)
    return fake


def _uid() -> str:
    return f"itest-{uuid4().hex}"


async def _always_connected(*_args: Any, **_kwargs: Any) -> bool:
    return True


async def _never_connected(*_args: Any, **_kwargs: Any) -> bool:
    return False


# --------------------------------------------------------------------------- #
# 1. Security — the path-traversal guard (the materializer backstop).          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "evil",
    ["../../pwned", "../escape", "..", "a/b", "/abs/path", "....//x", "with space", "x" * 65],
)
def test_materialize_skips_unsafe_integration_id(tmp_path: Path, evil: str) -> None:
    written = materialize_instructions(tmp_path, {evil: "malicious payload"})
    assert written == 0, f"unsafe id {evil!r} was materialized"
    # Nothing written under the root, and nothing escaped above it.
    assert list(tmp_path.rglob("instructions.md")) == []
    escape = (tmp_path / "integrations" / evil / "agent" / "instructions.md").resolve()
    assert not escape.exists()
    assert not (tmp_path.parent / "pwned").exists()
    assert not (tmp_path.parent.parent / "pwned").exists()


def test_materialize_writes_safe_and_skips_unsafe_together(tmp_path: Path) -> None:
    written = materialize_instructions(tmp_path, {"slack": "focus eng", "../../evil": "bad"})
    assert written == 1
    assert tmp_path.joinpath(*INSTR_REL).read_text() == "focus eng"
    assert not (tmp_path.parent.parent / "evil").exists()


# --------------------------------------------------------------------------- #
# 2. Session-bootstrap staleness gate (runs on every chat turn).               #
# --------------------------------------------------------------------------- #
def test_gate_resyncs_when_only_instructions_change(tmp_path: Path) -> None:
    h, connected = library_hash(), set()
    _materialize_if_stale(
        tmp_path, h, connected, {"slack": "v1"}, svc.instructions_signature({"slack": "v1"})
    )
    proj = tmp_path.joinpath(*INSTR_REL)
    assert proj.read_text() == "v1"

    # Skills hash + connected unchanged; ONLY the instructions signature differs.
    _materialize_if_stale(
        tmp_path, h, connected, {"slack": "v2"}, svc.instructions_signature({"slack": "v2"})
    )
    assert proj.read_text() == "v2", "gate ignored an instructions change"


def test_gate_is_noop_when_nothing_changed(tmp_path: Path) -> None:
    h, connected = library_hash(), set()
    instr = {"slack": "stable"}
    sig = svc.instructions_signature(instr)
    _materialize_if_stale(tmp_path, h, connected, instr, sig)
    proj = tmp_path.joinpath(*INSTR_REL)

    # Corrupt the projection, then re-run the gate with identical signatures.
    # A correct gate short-circuits and leaves the sentinel untouched; a gate
    # that re-materializes every turn would clobber it back to "stable".
    proj.write_text("SENTINEL")
    _materialize_if_stale(tmp_path, h, connected, instr, sig)
    assert proj.read_text() == "SENTINEL", "gate re-materialized when nothing changed"


def test_gate_removes_cleared_instruction(tmp_path: Path) -> None:
    h, connected = library_hash(), set()
    _materialize_if_stale(
        tmp_path, h, connected, {"slack": "x"}, svc.instructions_signature({"slack": "x"})
    )
    proj = tmp_path.joinpath(*INSTR_REL)
    assert proj.exists()
    _materialize_if_stale(tmp_path, h, connected, {}, svc.instructions_signature({}))
    assert not proj.exists(), "cleared instruction projection was not removed"


# --------------------------------------------------------------------------- #
# 3. Signature determinism (drives the gate).                                  #
# --------------------------------------------------------------------------- #
def test_signature_is_order_independent() -> None:
    assert svc.instructions_signature({"a": "1", "b": "2"}) == svc.instructions_signature(
        {"b": "2", "a": "1"}
    )


def test_signature_changes_on_any_content_change() -> None:
    base = svc.instructions_signature({"slack": "a"})
    assert base != svc.instructions_signature({"slack": "b"})
    assert base != svc.instructions_signature({"slack": "a", "github": "c"})


# --------------------------------------------------------------------------- #
# 4. Service round-trip, truncation, audit, isolation (real service logic).    #
# --------------------------------------------------------------------------- #
async def test_service_roundtrip_and_audit(fake_collection: FakeCollection) -> None:
    uid = _uid()
    await svc.upsert_instructions(uid, "slack", "focus #eng", InstructionsEditor.USER)
    rec = await svc.get_instructions_record(uid, "slack")
    assert rec is not None
    assert rec.content == "focus #eng"
    assert rec.updated_by == InstructionsEditor.USER
    assert await svc.get_all_instructions(uid) == {"slack": "focus #eng"}

    # Agent overwrite flips the audit field and replaces (not appends) content.
    await svc.upsert_instructions(uid, "slack", "default project backend", InstructionsEditor.AGENT)
    rec2 = await svc.get_instructions_record(uid, "slack")
    assert rec2.content == "default project backend"
    assert rec2.updated_by == InstructionsEditor.AGENT


async def test_service_truncates_to_cap(fake_collection: FakeCollection) -> None:
    uid = _uid()
    await svc.upsert_instructions(
        uid, "slack", "x" * (MAX_INSTRUCTIONS_CHARS + 500), InstructionsEditor.USER
    )
    rec = await svc.get_instructions_record(uid, "slack")
    assert len(rec.content) == MAX_INSTRUCTIONS_CHARS


async def test_service_is_user_scoped(fake_collection: FakeCollection) -> None:
    a, b = _uid(), _uid()
    await svc.upsert_instructions(a, "slack", "tenant-a-secret", InstructionsEditor.USER)
    assert await svc.get_instructions(b, "slack") is None
    assert await svc.get_all_instructions(b) == {}
    assert await svc.get_instructions(a, "slack") == "tenant-a-secret"


async def test_whitespace_only_is_treated_as_empty(fake_collection: FakeCollection) -> None:
    uid = _uid()
    await svc.upsert_instructions(uid, "slack", "   \n\t  ", InstructionsEditor.USER)
    # Whitespace-only guidance is meaningless — it must not surface as content.
    assert await svc.get_instructions(uid, "slack") in (None, "")
    assert "slack" not in await svc.get_all_instructions(uid)


# --------------------------------------------------------------------------- #
# 5. Agent tool — security + persistence (real tool, faked DB).                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("evil", ["../../x", "..", "a/b", "/abs", "with space", "x" * 65, "café"])
async def test_tool_rejects_unsafe_integration_id(
    fake_collection: FakeCollection, evil: str
) -> None:
    result = await tool_mod.update_integration_instructions.coroutine(
        config={"metadata": {"user_id": _uid()}}, integration_id=evil, content="hi"
    )
    assert "invalid" in result.lower()
    assert fake_collection.docs == [], "unsafe id was persisted"


async def test_tool_persists_and_is_readable(
    fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool_mod, "check_user_has_integration", _always_connected)
    uid = _uid()
    cfg = {"metadata": {"user_id": uid}}
    await tool_mod.update_integration_instructions.coroutine(
        config=cfg, integration_id="slack", content="always cc me"
    )
    assert await svc.get_instructions(uid, "slack") == "always cc me"
    read_back = await tool_mod.get_integration_instructions.coroutine(
        config=cfg, integration_id="slack"
    )
    assert "always cc me" in read_back


async def test_tool_rejects_unconnected_integration(
    fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A safe slug that the user has not added must not create an orphan record,
    # even though it passes the path-safety guard.
    monkeypatch.setattr(tool_mod, "check_user_has_integration", _never_connected)
    result = await tool_mod.update_integration_instructions.coroutine(
        config={"metadata": {"user_id": _uid()}}, integration_id="slack", content="hi"
    )
    assert "not one of" in result.lower()
    assert fake_collection.docs == [], "instructions persisted for an unconnected integration"


async def test_tool_requires_user_id(fake_collection: FakeCollection) -> None:
    result = await tool_mod.update_integration_instructions.coroutine(
        config={"metadata": {}}, integration_id="slack", content="hi"
    )
    assert "error" in result.lower()
    assert fake_collection.docs == []


# --------------------------------------------------------------------------- #
# 6. Subagent context injection (real _fetch_instructions_block).              #
# --------------------------------------------------------------------------- #
def _stub_integration(name: str):
    return type("Stub", (), {"name": name})()


async def test_context_block_injected_when_set(
    fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = _uid()
    await svc.upsert_instructions(
        uid, "slack", "focus on #eng and #design", InstructionsEditor.USER
    )
    monkeypatch.setattr(
        subagent_helpers, "get_integration_by_id", lambda _id: _stub_integration("Slack")
    )
    block = await subagent_helpers._fetch_instructions_block("slack", uid)
    assert "focus on #eng and #design" in block
    assert "SLACK" in block.upper()


async def test_context_block_empty_when_unset(fake_collection: FakeCollection) -> None:
    block = await subagent_helpers._fetch_instructions_block("slack", _uid())
    assert block == ""


async def test_context_block_empty_for_whitespace_only(
    fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = _uid()
    await svc.upsert_instructions(uid, "slack", "   ", InstructionsEditor.USER)
    monkeypatch.setattr(
        subagent_helpers, "get_integration_by_id", lambda _id: _stub_integration("Slack")
    )
    block = await subagent_helpers._fetch_instructions_block("slack", uid)
    assert block == "", "whitespace-only instructions produced a noisy context block"
