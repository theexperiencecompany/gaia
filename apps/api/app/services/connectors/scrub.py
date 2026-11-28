"""Remove a connector's secret from a call's output before the agent sees it.

The secret is matched raw, URL-encoded, JSON-escaped, hex and base64 (standard
and URL-safe, at every byte alignment, so it is caught inside a larger encoded
blob such as a basic-auth header), and across line breaks, which is how a
wrapped base64 dump or a CLI's column wrap would split it.
"""

import base64
from collections.abc import Iterable
import json
import re
from urllib.parse import quote, quote_plus

from app.constants.connectors import CONNECTOR_REDACTION

# Below this an encoded fragment is too short to be the secret rather than noise.
_MIN_VARIANT_CHARS = 8
_BASE64_GROUP_BYTES = 3
_BASE64_GROUP_CHARS = 4
# Characters of a base64 alignment's prefix that the padding bytes touch.
_PAD_CHARS = {0: 0, 1: 2, 2: 3}


def _base64_cores(secret: bytes) -> set[str]:
    """Return the base64 text the secret encodes to wherever it sits in a larger stream."""
    cores: set[str] = set()
    for offset in range(_BASE64_GROUP_BYTES):
        padded = b"\0" * offset + secret
        whole = len(padded) // _BASE64_GROUP_BYTES * _BASE64_GROUP_CHARS
        for encode in (base64.b64encode, base64.urlsafe_b64encode):
            core = encode(padded).decode()[_PAD_CHARS[offset] : whole]
            if len(core) >= _MIN_VARIANT_CHARS:
                cores.add(core)
    return cores


def secret_variants(secret: str) -> set[str]:
    """Return every form of the secret the scrubber looks for."""
    raw = secret.encode()
    variants = {
        secret,
        quote(secret, safe=""),
        quote_plus(secret, safe=""),
        json.dumps(secret)[1:-1],
        raw.hex(),
        raw.hex().upper(),
        *_base64_cores(raw),
    }
    return {variant for variant in variants if variant}


def _split_tolerant(variant: str) -> str:
    """Return a pattern matching the variant even with line breaks or spaces between its characters."""
    return r"\s*".join(re.escape(char) for char in variant)


def secret_pattern(secrets: Iterable[str]) -> re.Pattern[str] | None:
    """Compile one pattern for every variant of every secret, longest first; None when there is none."""
    variants = {variant for secret in secrets if secret for variant in secret_variants(secret)}
    if not variants:
        return None
    ordered = sorted(variants, key=len, reverse=True)
    return re.compile("|".join(_split_tolerant(variant) for variant in ordered))


def scrub(text: str, pattern: re.Pattern[str] | None) -> str:
    """Replace every match of the secret pattern with the redaction marker."""
    if pattern is None or not text:
        return text
    return pattern.sub(CONNECTOR_REDACTION, text)
