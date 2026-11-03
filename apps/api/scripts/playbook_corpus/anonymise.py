"""Strip a prod run of what identifies a person while keeping what the playbook checks read.

What survives is structure: keys, list lengths, value types, placeholder
tokens, tool and integration names, and every date or time (a time slot's
layout is read off the recorded value). Words are replaced by salted
look-alikes of the same length and case, ids and digits by salted hashes,
emails and links by fixed stand-ins. The salt is drawn fresh per capture and
never stored, so a fixture cannot be reversed by guessing.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
import hashlib
import json
import re
import secrets

from app.models.workflow_execution_models import RecordedCall, build_result_digest, parse_result
from app.services.workflow.playbook.placeholders import PLACEHOLDER_TOKEN

EMAIL = "user@example.com"
LINK = "https://example.com/"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LINK = re.compile(r"https?://\S+")
#: A strftime directive inside a layout an author wrote ("%Y-%m-%d"): kept, it is syntax.
_DIRECTIVE = re.compile(r"%:?[A-Za-z]")
#: An ISO date or datetime, or a short numeric date or clock time: kept whole.
_DATE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"|\d{1,2}[/:.]\d{1,2}(?:[/:.]\d{2,4})?"
)
#: A run of characters treated as one unit: a placeholder, a link, an email, a date, a word.
_UNIT = re.compile(
    rf"{PLACEHOLDER_TOKEN.pattern}|{_LINK.pattern}|{_EMAIL.pattern}|{_DATE.pattern}"
    rf"|{_DIRECTIVE.pattern}|[A-Za-z0-9]+"
)
#: Digits this short are a day, a year or a count, not an identifier.
_SHORT_NUMBER = re.compile(r"\d{1,4}")
#: Words that carry no identity and that a date layout reads (%B, %A, %p).
_KEPT_WORDS = frozenset(
    word.lower()
    for word in [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Sept",
        "Oct",
        "Nov",
        "Dec",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
        "Sat",
        "Sun",
        "AM",
        "PM",
        "UTC",
        "GMT",
        "T",
        "Z",
    ]
)
_LOWER = "abcdefghijklmnopqrstuvwxyz"
_DIGITS = "0123456789"
_HEX_LIKE = re.compile(r"[0-9a-f-]{8,}")


@dataclass(frozen=True, slots=True)
class Anonymiser:
    """One capture's salt, and the names that are vocabulary rather than data."""

    salt: bytes
    kept: frozenset[str]

    @classmethod
    def fresh(cls, kept: Collection[str]) -> Anonymiser:
        return cls(salt=secrets.token_bytes(16), kept=frozenset(kept))

    def call(self, call: RecordedCall) -> RecordedCall:
        """Return the call with its args, result and dispatch ids anonymised."""
        return call.model_copy(
            update={
                "args": self.value(call.args),
                "result_digest": self.digest(call.result_digest),
                "subagent": None if call.subagent is None else self.name(call.subagent),
                "subagent_id": None,
                "account": None if call.account is None else self.text(call.account),
            }
        )

    def name_of_run(self, execution_id: str) -> str:
        """A run's fixture name: stable within one capture, unlinkable to the execution."""
        return f"run_{self._digest(execution_id).hex()[:12]}"

    def digest(self, digest: str) -> str:
        parsed = parse_result(digest)
        if isinstance(parsed, str):
            return build_result_digest(self.text(parsed))
        return build_result_digest(json.dumps(self.value(parsed)))

    def name(self, value: str) -> str:
        """An integration or subagent id: kept when it is vocabulary, hashed when it is a row id."""
        return value if value in self.kept or not _HEX_LIKE.fullmatch(value) else self._hash(value)

    def value(self, value: object) -> object:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {
                (self.text(key) if "@" in key else key): self.value(item)
                for key, item in value.items()
            }
        return value

    def text(self, text: str) -> str:
        if text in self.kept:
            return text
        return _UNIT.sub(lambda match: self._unit(match.group(0)), text)

    def _unit(self, unit: str) -> str:
        if PLACEHOLDER_TOKEN.fullmatch(unit) or unit in self.kept:
            return unit
        if _EMAIL.fullmatch(unit):
            return EMAIL
        if _LINK.fullmatch(unit):
            return LINK + self._hash(unit)[:8]
        if (
            _DATE.fullmatch(unit)
            or _DIRECTIVE.fullmatch(unit)
            or _SHORT_NUMBER.fullmatch(unit)
            or unit.lower() in _KEPT_WORDS
        ):
            return unit
        return "".join(self._char(unit, index, char) for index, char in enumerate(unit))

    def _char(self, unit: str, index: int, char: str) -> str:
        """A salted stand-in for one character of a unit, of the same class."""
        if char.isdigit():
            alphabet = _DIGITS
        elif char.isalpha():
            alphabet = _LOWER
        else:
            return char
        pick = self._digest(f"{unit}\0{index}")[0] % len(alphabet)
        replaced = alphabet[pick]
        return replaced.upper() if char.isupper() else replaced

    def _hash(self, value: str) -> str:
        return self._digest(value).hex()[: max(8, min(len(value), 24))]

    def _digest(self, value: str) -> bytes:
        return hashlib.blake2b(value.encode(), key=self.salt, digest_size=16).digest()
