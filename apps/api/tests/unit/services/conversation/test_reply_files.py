"""reply_files: each file a reply's cards wrote, once per path, in the order they were written."""

from app.constants.chat import ARTIFACT_CARD
from app.services.conversation.reply_files import reply_files
from shared.py.conversation_wire import ReplyFile, ToolDataEntry


def _artifact(event: str, path: str, content_type: str | None = None) -> ToolDataEntry:
    return {
        "tool_name": ARTIFACT_CARD,
        "data": {"event": event, "path": path, "content_type": content_type},
    }


def test_each_written_file_is_listed_once_with_its_type_past_other_cards() -> None:
    cards: list[ToolDataEntry] = [
        _artifact("upsert", "/a/report.pdf", "application/pdf"),
        {"tool_name": "search", "data": {"q": "x"}},
        _artifact("delete", "/a/old.txt"),
        _artifact("upsert", "/a/chart.png", "image/png"),
        _artifact("upsert", "/a/report.pdf", "text/plain"),
    ]

    page = "https://app.test/c/c1"

    assert reply_files(cards, page) == (
        ReplyFile(path="/a/report.pdf", content_type="application/pdf", opens_at=page),
        ReplyFile(path="/a/chart.png", content_type="image/png", opens_at=page),
    )


def test_a_file_carries_the_link_its_writing_tool_attached() -> None:
    """Regression: the runtime merge dropped the short link a bot captions a file message with."""
    linked: ToolDataEntry = {
        "tool_name": ARTIFACT_CARD,
        "data": {
            "event": "upsert",
            "path": "report.pdf",
            "content_type": "application/pdf",
            "short_url": "https://heygaia.link/ab12cd",
        },
    }
    page = "https://app.test/c/c1"

    assert reply_files([_artifact("upsert", "report.pdf", "application/pdf"), linked], page) == (
        ReplyFile(
            path="report.pdf",
            content_type="application/pdf",
            opens_at=page,
            short_url="https://heygaia.link/ab12cd",
        ),
    )
