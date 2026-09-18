"""The outbound envelope's validation rules: one attachment source, and which URLs may be http."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from pydantic import BaseModel, ValidationError
import pytest

from app.config.settings import settings
from app.schemas.outbound import OutboundAttachment, OutboundMessageEnvelope

_ONE_SOURCE = "attachment requires exactly one of `url` or (`conversation_id` + `path`)"
_HTTPS_ONLY = "attachment `url` must be an https URL"
_NEEDS_BODY = "envelope requires text, text_parts, or attachment"


def _rejection(build: Callable[[], BaseModel]) -> str:
    """Return the message the single validation error carries, verbatim."""
    with pytest.raises(ValidationError) as raised:
        build()
    (error,) = raised.value.errors()
    return str(error["ctx"]["error"])


def _artifact(**overrides: object) -> dict[str, object]:
    return {
        "conversation_id": "conv-1",
        "path": "shots/step-1.png",
        "filename": "step-1.png",
    } | overrides


@pytest.mark.unit
class TestAttachmentSource:
    def test_an_artifact_pair_is_a_valid_source(self) -> None:
        attachment = OutboundAttachment(**_artifact())
        assert (attachment.conversation_id, attachment.path) == ("conv-1", "shots/step-1.png")
        assert attachment.url is None

    def test_a_cdn_url_is_a_valid_source(self) -> None:
        attachment = OutboundAttachment(url="https://cdn.example/a.png", filename="a.png")
        assert attachment.url == "https://cdn.example/a.png"
        assert attachment.path is None

    def test_no_source_at_all_is_rejected(self) -> None:
        assert _rejection(lambda: OutboundAttachment(filename="a.png")) == _ONE_SOURCE

    def test_both_sources_at_once_is_rejected(self) -> None:
        both = _artifact(url="https://cdn.example/a.png")
        assert _rejection(partial(OutboundAttachment, **both)) == _ONE_SOURCE

    @pytest.mark.parametrize("missing", ["conversation_id", "path"])
    def test_half_an_artifact_pair_is_not_a_source(self, missing: str) -> None:
        assert _rejection(lambda: OutboundAttachment(**_artifact(**{missing: None}))) == _ONE_SOURCE

    def test_half_an_artifact_pair_alongside_a_url_leaves_exactly_one_source(self) -> None:
        attachment = OutboundAttachment(**_artifact(path=None, url="https://cdn.example/a.png"))
        assert attachment.url == "https://cdn.example/a.png"


@pytest.mark.unit
class TestAttachmentUrlScheme:
    @pytest.mark.parametrize(
        "url",
        ["http://cdn.example/a.png", "ftp://cdn.example/a.png", "HTTPS://cdn.example/a.png"],
    )
    def test_a_non_https_url_is_rejected(self, url: str) -> None:
        assert _rejection(lambda: OutboundAttachment(url=url, filename="a.png")) == _HTTPS_ONLY

    def test_the_scheme_rule_does_not_apply_to_an_artifact_source(self) -> None:
        assert OutboundAttachment(**_artifact()).url is None


@pytest.mark.unit
class TestAttachmentUrlOnThisApi:
    """http is allowed only for this API's own URLs, where the bot authenticates the fetch."""

    @pytest.fixture(autouse=True)
    def _own_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "HOST", "http://localhost:8480")

    def test_this_apis_own_http_url_is_accepted(self) -> None:
        url = "http://localhost:8480/shots/c0de/1.png"
        assert OutboundAttachment(url=url, filename="1.png").url == url

    @pytest.mark.parametrize(
        "url",
        [
            # Another host entirely, while ours happens to be http.
            "http://cdn.example/a.png",
            # Our host as a path or a query, which a prefix test would wave through.
            "http://cdn.example/http://localhost:8480/a.png",
            "http://cdn.example/a.png?u=http://localhost:8480",
            # Our host, another port.
            "http://localhost:9999/shots/c0de/1.png",
            # Our host as someone else's subdomain.
            "http://localhost:8480.evil.example/a.png",
        ],
    )
    def test_an_http_url_that_is_not_this_api_is_still_rejected(self, url: str) -> None:
        assert _rejection(lambda: OutboundAttachment(url=url, filename="a.png")) == _HTTPS_ONLY

    def test_a_different_scheme_on_our_host_is_not_this_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Served over https, so an http link to the same host is someone downgrading it.
        monkeypatch.setattr(settings, "HOST", "https://api.heygaia.io")
        assert (
            _rejection(lambda: OutboundAttachment(url="http://api.heygaia.io/a.png", filename="a"))
            == _HTTPS_ONLY
        )

    def test_no_configured_host_exempts_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "HOST", "")
        assert (
            _rejection(lambda: OutboundAttachment(url="http://localhost:8480/a.png", filename="a"))
            == _HTTPS_ONLY
        )


@pytest.mark.unit
class TestEnvelopeBody:
    def test_an_envelope_needs_text_parts_or_an_attachment(self) -> None:
        bodyless = partial(OutboundMessageEnvelope, platform="slack", destination_id="C1")
        assert _rejection(bodyless) == _NEEDS_BODY

    def test_an_attachment_only_envelope_is_valid(self) -> None:
        envelope = OutboundMessageEnvelope(
            platform="slack",
            destination_id="C1",
            attachment=OutboundAttachment(**_artifact()),
        )
        assert envelope.text is None
        assert envelope.is_channel is False
        assert envelope.enqueued_at.tzinfo is not None

    def test_every_envelope_gets_its_own_id(self) -> None:
        made = [
            OutboundMessageEnvelope(platform="slack", destination_id="C1", text="hi")
            for _ in range(2)
        ]
        assert made[0].id != made[1].id
