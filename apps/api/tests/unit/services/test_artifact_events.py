"""The artifact card payloads: a file in a session's artifacts/ appeared, changed, or went away."""

from app.services.artifact_events import remove_event, upsert_event
from app.services.storage import ArtifactInfo


def test_a_written_file_is_carded_with_what_the_listing_says_of_it() -> None:
    info = ArtifactInfo(path="out/report.csv", size_bytes=3, mtime=1_000.0, content_type="text/csv")
    assert upsert_event("c1", info) == {
        "event": "upsert",
        "session_id": "c1",
        "path": "out/report.csv",
        "size_bytes": 3,
        "mtime": 1_000.0,
        "content_type": "text/csv",
    }


def test_a_deleted_file_is_carded_for_removal_by_its_path() -> None:
    assert remove_event("c1", "out/report.csv") == {
        "event": "remove",
        "session_id": "c1",
        "path": "out/report.csv",
    }
