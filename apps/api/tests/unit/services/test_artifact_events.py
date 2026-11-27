"""The artifact card payloads: a file in a session's artifacts/ appeared, changed, or went away."""

from app.constants.chat import ARTIFACT_CARD
from app.models.tool_card_registry import tool_card_data
from app.services.artifact_events import remove_event, upsert_event
from app.services.storage import ArtifactInfo


def test_a_written_file_is_carded_with_what_the_listing_says_of_it() -> None:
    info = ArtifactInfo(path="out/report.csv", size_bytes=3, mtime=1_000.0, content_type="text/csv")
    # No link attached: the card carries no short_url key at all, not a null one.
    assert tool_card_data(ARTIFACT_CARD, upsert_event("c1", info)) == {
        "event": "upsert",
        "session_id": "c1",
        "path": "out/report.csv",
        "size_bytes": 3,
        "mtime": 1_000.0,
        "content_type": "text/csv",
    }


def test_a_deleted_file_is_carded_for_removal_by_its_path() -> None:
    assert tool_card_data(ARTIFACT_CARD, remove_event("c1", "out/report.csv")) == {
        "event": "remove",
        "session_id": "c1",
        "path": "out/report.csv",
    }


def test_the_link_the_writing_tool_attached_is_carried() -> None:
    info = ArtifactInfo(path="out/report.csv", size_bytes=3, mtime=1_000.0, content_type="text/csv")
    short_url = "https://heygaia.link/abcdefghijk"
    card = tool_card_data(ARTIFACT_CARD, upsert_event("c1", info, short_url=short_url))
    assert isinstance(card, dict)
    assert card["short_url"] == short_url
