"""Spike: Composio-native auto-upload interop (FileHelper + our path mapping).

Proves hermetically — Composio's HTTP is stubbed, no credentials needed — that:
- a ``file_uploadable``-marked schema leaf taking a path string is uploaded and
  substituted with the ``{name, mimetype, s3key}`` dict the tool expects, as a
  bare object for a single file (what Gmail's pinned tools take);
- our sandbox→host mapping feeds that pipeline correctly shaped values;
- the ``before_file_upload`` context carries no user identity (the spike's
  load-bearing blocker for per-user containment — pinned here, see verdict).

If this ever needs real credentials it belongs in tests/composio/.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.composio.attachments import map_sandbox_path_for_upload

MODULE = "app.services.composio.attachments"


def _tool(input_parameters: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        slug="GMAIL_SEND_EMAIL",
        toolkit=SimpleNamespace(slug="gmail"),
        input_parameters=input_parameters,
    )


def _marked_attachment_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "attachment": {
                "type": "object",
                "file_uploadable": True,
                "properties": {
                    "name": {"type": "string"},
                    "mimetype": {"type": "string"},
                    "s3key": {"type": "string"},
                },
            },
            "subject": {"type": "string"},
        },
    }


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.post.return_value = SimpleNamespace(
        new_presigned_url="https://s3.invalid/upload", key="k/1"
    )
    return client


def _seed_pdf(tmp_path: Path) -> Path:
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4 spike")
    return target


class TestNativeSubstitution:
    def test_marked_leaf_path_becomes_upload_dict(self, tmp_path: Path) -> None:
        from composio.core.models._files import FileHelper

        seeded = _seed_pdf(tmp_path)
        request: dict[str, Any] = {"attachment": str(seeded), "subject": "hi"}
        with patch("requests.put", return_value=SimpleNamespace(status_code=200)):
            out = FileHelper(client=_fake_client()).substitute_file_uploads(
                tool=_tool(_marked_attachment_schema()), request=request
            )

        assert out is request  # mutated in place, identity preserved
        uploaded = request["attachment"]
        assert isinstance(uploaded, dict)  # bare object, not a list
        assert uploaded == {
            "name": "report.pdf",
            "mimetype": "application/pdf",
            "s3key": "k/1",
        }
        assert request["subject"] == "hi"

    def test_before_file_upload_rewrites_sandbox_path(self, tmp_path: Path) -> None:
        from composio.core.models._files import FileHelper

        seeded = _seed_pdf(tmp_path)
        seen: list[dict[str, Any]] = []

        def _map(ctx: dict[str, Any]) -> str:
            # Stands in for map_sandbox_path_for_upload: sandbox reference in,
            # contained host path out.
            seen.append(dict(ctx))
            return str(seeded)

        request: dict[str, Any] = {"attachment": "/workspace/sessions/c/report.pdf"}
        with patch("requests.put", return_value=SimpleNamespace(status_code=200)):
            FileHelper(client=_fake_client()).substitute_file_uploads(
                tool=_tool(_marked_attachment_schema()),
                request=request,
                before_file_upload=_map,  # type: ignore[arg-type]
            )

        assert request["attachment"]["name"] == "report.pdf"
        # The blocker, pinned: path/source/tool/toolkit only — per-user
        # containment cannot plug in here without smuggled identity.
        assert seen[0]["path"] == "/workspace/sessions/c/report.pdf"
        assert seen[0]["tool"] == "GMAIL_SEND_EMAIL"
        assert "user_id" not in seen[0]


class TestMapSandboxPathForUpload:
    def test_workspace_path_resolves_contained(self) -> None:
        with patch(
            f"{MODULE}.resolve_user_file_sync",
            return_value=Path("/mnt/jfs/users/u1/sessions/c/x.pdf"),
        ) as res:
            out = map_sandbox_path_for_upload("/workspace/sessions/c/x.pdf", user_id="u1")
        assert res.call_args.args == ("u1", "sessions/c/x.pdf")
        assert out == "/mnt/jfs/users/u1/sessions/c/x.pdf"

    def test_bare_relative_path_resolves(self) -> None:
        with patch(
            f"{MODULE}.resolve_user_file_sync",
            return_value=Path("/mnt/jfs/users/u1/a.txt"),
        ) as res:
            map_sandbox_path_for_upload("a.txt", user_id="u1")
        assert res.call_args.args == ("u1", "a.txt")

    def test_url_passes_through_unresolved(self) -> None:
        with patch(f"{MODULE}.resolve_user_file_sync") as res:
            out = map_sandbox_path_for_upload("https://drive/download/1", user_id="u1")
        assert res.called is False
        assert out == "https://drive/download/1"

    @pytest.mark.parametrize("bad", ["/etc/passwd", "/mnt/jfs/users/other/x.pdf"])
    def test_non_workspace_absolute_path_raises(self, bad: str) -> None:
        # ("../" escape inside /workspace/ is resolve_user_file_sync's tested
        # job — the mapping only refuses paths outside the sandbox root.)
        with (
            patch(f"{MODULE}.resolve_user_file_sync") as res,
            pytest.raises(ValueError, match="refusing to upload"),
        ):
            map_sandbox_path_for_upload(bad, user_id="u1")
        assert res.called is False
