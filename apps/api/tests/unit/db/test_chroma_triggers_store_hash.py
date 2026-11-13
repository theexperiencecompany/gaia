"""A trigger written through ChromaStore reads back with its hash, so an unchanged one is not re-embedded."""

import pytest

from app.db.chroma.chroma_store import ChromaStore
from app.db.chroma.chroma_triggers_store import (
    TRIGGERS_NAMESPACE,
    _build_put_operations,
    _compute_trigger_diff,
    _get_existing_triggers_from_chroma,
)
from tests._harness.chroma_fakes import FakeChromaClient, FakeChromaCollection


@pytest.mark.unit
@pytest.mark.regression
async def test_an_unchanged_trigger_is_not_upserted_again_on_the_next_boot() -> None:
    collection = FakeChromaCollection()
    store = ChromaStore(client=FakeChromaClient(collection), collection_name="triggers")
    entry = {
        "hash": "hash_new_email",
        "slug": "GMAIL_NEW_EMAIL",
        "name": "New email",
        "description": "Fires on a new email",
        "integration_id": "gmail",
        "integration_name": "Gmail",
        "category": "communication",
        "rich_description": "New email. Fires on a new email.",
    }
    await store.abatch(_build_put_operations([("GMAIL_NEW_EMAIL", entry)], []))

    existing = await _get_existing_triggers_from_chroma(collection)
    to_upsert, to_delete = _compute_trigger_diff({"GMAIL_NEW_EMAIL": entry}, existing)

    assert existing == {
        "GMAIL_NEW_EMAIL": {"hash": "hash_new_email", "namespace": TRIGGERS_NAMESPACE}
    }
    assert (to_upsert, to_delete) == ([], [])
