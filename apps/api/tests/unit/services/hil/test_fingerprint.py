"""Canonical fingerprints for approval dedup (exact bytes, never fuzzy)."""

from datetime import datetime

import pytest

from app.services.hil.fingerprint import approval_fingerprint


@pytest.mark.unit
class TestApprovalFingerprint:
    def test_same_call_same_fingerprint_despite_key_order(self) -> None:
        a = approval_fingerprint("GMAIL_SEND_EMAIL", {"to": "b@x", "subject": "hi"})
        b = approval_fingerprint("GMAIL_SEND_EMAIL", {"subject": "hi", "to": "b@x"})
        assert a == b

    def test_arg_change_new_fingerprint(self) -> None:
        a = approval_fingerprint("GMAIL_SEND_EMAIL", {"to": "b@x"})
        b = approval_fingerprint("GMAIL_SEND_EMAIL", {"to": "c@x"})
        assert a != b

    def test_tool_change_new_fingerprint(self) -> None:
        a = approval_fingerprint("GMAIL_SEND_EMAIL", {"to": "b@x"})
        b = approval_fingerprint("GMAIL_DELETE_EMAIL", {"to": "b@x"})
        assert a != b

    def test_none_args_equals_empty_args(self) -> None:
        assert approval_fingerprint("T", None) == approval_fingerprint("T", {})

    def test_fingerprint_is_stable_hex(self) -> None:
        fp = approval_fingerprint("T", {"a": [1, {"b": 2}]})
        assert len(fp) == 32
        int(fp, 16)

    def test_fingerprint_bytes_are_pinned_so_stored_rows_still_dedup(self) -> None:
        """Live ledger rows are matched by this value, so any drift orphans them."""
        assert approval_fingerprint("GMAIL_SEND_EMAIL", {"to": "b@x"}) == (
            "9807ab5780a9a2795e7638b44eb0b945"
        )

    def test_non_json_args_fingerprint_by_their_string_form(self) -> None:
        fp = approval_fingerprint("T", {"at": datetime(2026, 1, 1)})
        assert fp == "d34efa5d905c69678f77567655015228"
