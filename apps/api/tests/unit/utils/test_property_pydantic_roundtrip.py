"""Property-based round-trip tests for Pydantic schemas.

Every property states a serialization invariant and lets Hypothesis hunt for
a counterexample:

- ``model_dump()`` -> ``model_validate()`` must be lossless for any valid model.
- The wire path (``model_dump_json`` with aliases) must round-trip through
  ``model_validate_json`` without losing or mis-mapping fields.
- Datetimes must stay tz-aware and UTC-equivalent through both paths.

If a field gained a serialization alias that collides, a default_factory got
dropped, or a datetime lost its timezone, one of these properties fails.
"""

from datetime import UTC, timedelta
from typing import Any

from hypothesis import given, settings, strategies as st
import pytest

from app.models.integration_instructions_models import InstructionsEditor
from app.schemas.integrations.responses import IntegrationInstructionsResponse
from app.schemas.outbound import OutboundAttachment, OutboundMessageEnvelope

UTC_OFFSET_ZERO = timedelta(0)


def _is_aware_utc(dt: Any) -> bool:
    return dt.tzinfo is not None and dt.utcoffset() == UTC_OFFSET_ZERO


# ---------------------------------------------------------------------------
# OutboundMessageEnvelope — payload presence invariant + round-trip
# ---------------------------------------------------------------------------


@st.composite
def valid_envelope(draw: st.DrawFn) -> OutboundMessageEnvelope:
    """Envelope with at least one non-empty payload, per the model validator."""
    platform = draw(st.text(min_size=1, max_size=50))
    destination_id = draw(st.text(min_size=1, max_size=50))
    text = draw(st.one_of(st.none(), st.text(min_size=1, max_size=200)))
    text_parts = draw(
        st.one_of(st.none(), st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=5))
    )
    attachment = draw(
        st.one_of(
            st.none(),
            st.builds(
                OutboundAttachment,
                conversation_id=st.text(min_size=1, max_size=50),
                path=st.text(min_size=1, max_size=100),
                filename=st.text(min_size=1, max_size=100),
                content_type=st.one_of(st.none(), st.text(max_size=50)),
                caption=st.one_of(st.none(), st.text(max_size=200)),
            ),
        )
    )
    if text is None and text_parts is None and attachment is None:
        text = "fallback payload"
    return OutboundMessageEnvelope(
        platform=platform,
        destination_id=destination_id,
        text=text,
        text_parts=text_parts,
        attachment=attachment,
    )


class TestOutboundEnvelopeRoundTrip:
    @settings(deadline=None)
    @given(envelope=valid_envelope())
    def test_python_dump_round_trips_losslessly(self, envelope: OutboundMessageEnvelope) -> None:
        restored = OutboundMessageEnvelope.model_validate(envelope.model_dump())
        assert restored == envelope
        # Pydantic v2 re-validates on the way back in and builds a fresh
        # timezone.utc equivalent — the invariant is "aware, UTC offset zero",
        # not singleton identity.
        assert _is_aware_utc(restored.enqueued_at)

    @settings(deadline=None)
    @given(envelope=valid_envelope())
    def test_json_round_trip_preserves_wire_shape(self, envelope: OutboundMessageEnvelope) -> None:
        restored = OutboundMessageEnvelope.model_validate_json(envelope.model_dump_json())
        assert restored == envelope
        # The wire path re-parses the offset, so it is a fresh timezone.utc
        # equivalent, not the UTC singleton.
        assert _is_aware_utc(restored.enqueued_at)

    @settings(deadline=None)
    @given(envelope=valid_envelope())
    def test_json_has_exactly_the_declared_keys(self, envelope: OutboundMessageEnvelope) -> None:
        import json

        payload = json.loads(envelope.model_dump_json())
        assert set(payload) == {
            "id",
            "platform",
            "destination_id",
            "text",
            "text_parts",
            "attachment",
            "enqueued_at",
        }
        assert payload["text"] == envelope.text
        assert payload["text_parts"] == envelope.text_parts

    def test_default_enqueued_at_is_aware_utc(self) -> None:
        envelope = OutboundMessageEnvelope(platform="telegram", destination_id="42", text="hi")
        assert _is_aware_utc(envelope.enqueued_at)
        # The default_factory itself constructs the UTC singleton.
        assert envelope.enqueued_at.tzinfo is UTC

    @settings(deadline=None)
    @given(
        platform=st.text(min_size=1, max_size=50),
        destination_id=st.text(min_size=1, max_size=50),
        text=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
        text_parts=st.one_of(
            st.none(), st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=4)
        ),
    )
    def test_payload_presence_invariant(
        self, platform: str, destination_id: str, text: str | None, text_parts: list[str] | None
    ) -> None:
        kwargs: dict[str, Any] = {"platform": platform, "destination_id": destination_id}
        if text is not None:
            kwargs["text"] = text
        if text_parts is not None:
            kwargs["text_parts"] = text_parts
        has_payload = bool(text) or bool(text_parts)
        if has_payload:
            envelope = OutboundMessageEnvelope(**kwargs)
            assert OutboundMessageEnvelope.model_validate(envelope.model_dump()) == envelope
        else:
            # A present-but-empty text_parts list counts as no payload: the
            # validator must still reject the envelope.
            with pytest.raises(ValueError):
                OutboundMessageEnvelope(**kwargs)


# ---------------------------------------------------------------------------
# IntegrationInstructionsResponse — camelCase alias round-trip
# ---------------------------------------------------------------------------

CAMEL_SCHEMA_FIELDS = {
    "integration_id": "integrationId",
    "content": "content",
    "updated_by": "updatedBy",
    "updated_at": "updatedAt",
}


class TestCamelCaseAliasRoundTrip:
    @settings(deadline=None)
    @given(
        integration_id=st.text(min_size=1, max_size=50),
        content=st.text(max_size=8000),
        updated_by=st.sampled_from(list(InstructionsEditor)),
        updated_at=st.one_of(st.none(), st.datetimes(timezones=st.just(UTC))),
    )
    def test_alias_dump_validates_back_to_equal_model(
        self,
        integration_id: str,
        content: str,
        updated_by: InstructionsEditor,
        updated_at: Any,
    ) -> None:
        model = IntegrationInstructionsResponse(
            integration_id=integration_id,
            content=content,
            updated_by=updated_by,
            updated_at=updated_at,
        )
        alias_dump = model.model_dump(by_alias=True)
        assert set(alias_dump) == set(CAMEL_SCHEMA_FIELDS.values())
        restored = IntegrationInstructionsResponse.model_validate(alias_dump)
        assert restored == model
        # A JSON wire round-trip must preserve the instant and its zone.
        json_restored = IntegrationInstructionsResponse.model_validate_json(
            model.model_dump_json(by_alias=True)
        )
        assert json_restored == model
        if updated_at is not None:
            assert json_restored.updated_at is not None
            assert json_restored.updated_at == updated_at
            assert _is_aware_utc(json_restored.updated_at)
