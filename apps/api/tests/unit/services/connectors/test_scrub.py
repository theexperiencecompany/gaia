"""The secret never survives into a connector call's output, in any encoding the output might carry."""

import base64
import json
import textwrap
from urllib.parse import quote

from app.constants.connectors import CONNECTOR_REDACTION
from app.services.connectors.scrub import scrub, secret_pattern

SECRET = "ghp_R3alS3cr3t/Token+With=Odd&Chars_0123456789"


def _scrubbed(text: str) -> str:
    return scrub(text, secret_pattern([SECRET]))


def test_the_raw_secret_is_redacted_everywhere_it_appears() -> None:
    out = _scrubbed(f"GH_TOKEN={SECRET}\nagain: {SECRET}")

    assert SECRET not in out
    assert out.count(CONNECTOR_REDACTION) == 2


def test_the_url_encoded_secret_is_redacted() -> None:
    out = _scrubbed(f"GET /api?token={quote(SECRET, safe='')}")

    assert quote(SECRET, safe="") not in out
    assert CONNECTOR_REDACTION in out


def test_the_json_escaped_secret_is_redacted() -> None:
    out = _scrubbed(json.dumps({"token": SECRET}))

    assert json.dumps(SECRET)[1:-1] not in out


def test_the_secret_inside_a_basic_auth_header_is_redacted_at_every_alignment() -> None:
    for user in ("x", "xy", "xyz"):
        header = base64.b64encode(f"{user}:{SECRET}".encode()).decode()
        out = _scrubbed(f"Authorization: Basic {header}")

        # The part of the header that encodes the secret is gone; at most a few edge characters remain.
        assert CONNECTOR_REDACTION in out
        assert header[8:-4] not in out
        assert len(out.replace(CONNECTOR_REDACTION, "")) < len("Authorization: Basic ") + 12


def test_a_base64_dump_wrapped_across_lines_is_redacted() -> None:
    wrapped = "\n".join(textwrap.wrap(base64.b64encode(SECRET.encode()).decode(), 20))

    out = _scrubbed(f"env dump:\n{wrapped}\n")

    assert CONNECTOR_REDACTION in out
    assert base64.b64encode(SECRET.encode()).decode()[:20] not in out


def test_the_raw_secret_split_by_a_line_break_is_redacted() -> None:
    out = _scrubbed(f"token: {SECRET[:20]}\n{SECRET[20:]}")

    assert SECRET[:20] not in out
    assert SECRET[20:] not in out


def test_the_hex_secret_is_redacted() -> None:
    out = _scrubbed(SECRET.encode().hex())

    assert out == CONNECTOR_REDACTION


def test_output_without_the_secret_is_untouched() -> None:
    text = '{"login": "octocat", "id": 1}\nHTTP 200\n'

    assert _scrubbed(text) == text


def test_no_secret_means_no_scrubbing() -> None:
    assert secret_pattern([""]) is None
    assert scrub("anything", None) == "anything"
