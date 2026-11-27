"""Overwrite every string a policy does not keep with fake text, deterministically per run.

Equal inputs map to equal outputs within one run (one random key, never stored), so unique
indexes and cross-collection references still hold. Output length equals input length, so
document and index sizes stay realistic. A kept string or object key the PII guard flags is
replaced like any other string and counted by path, so a personal value never reaches the writer.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import hmac
import random
import re
import secrets
from typing import Any

from faker.providers.lorem.en_US import Provider as LoremProvider

from gaia_db_migration.model_policy import CollectionPolicy, Rule, StringRule
from gaia_db_migration.paths import ARRAY_MARKER
from gaia_db_migration.pii import PiiGuard, is_opaque_id

WORDS: tuple[str, ...] = tuple(LoremProvider.word_list)
FAKE_EMAIL_DOMAIN = "example.org"
TOKEN_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
KEYS_PATH = "<object key>"


#: A key repeated this often at one path across prod is schema, not personal data.
SCHEMA_KEY_MIN_OCCURRENCES = 20
IDENTIFIER_SHAPED_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def schema_keys(inventory: Mapping[str, Any]) -> frozenset[tuple[str, str, str]]:
    """Return (collection, parent path, key) for every identifier-shaped key prod repeats at its path."""
    found: set[tuple[str, str, str]] = set()
    for collection, profile in inventory["collections"].items():
        for path, stats in profile["paths"].items():
            parent, _, key = path.rpartition(".")
            if stats["present"] >= SCHEMA_KEY_MIN_OCCURRENCES and IDENTIFIER_SHAPED_KEY.fullmatch(
                key
            ):
                found.add((collection, parent, key))
    return frozenset(found)


@dataclass
class Anonymiser:
    """One run's key, its PII guard, and the paths where the guard replaced a kept value."""

    guard: PiiGuard
    schema: frozenset[tuple[str, str, str]]
    collection: str = ""
    key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    replaced: Counter[str] = field(default_factory=Counter)

    def document(self, document: Mapping[str, Any], policy: CollectionPolicy) -> dict[str, Any]:
        return {
            self._key(key, ""): self._value(value, key, policy) for key, value in document.items()
        }

    def _value(self, value: object, path: str, policy: CollectionPolicy) -> object:
        if isinstance(value, str):
            return self._string(value, path, policy.rule(path))
        if isinstance(value, Mapping):
            return {
                self._key(key, path): self._value(child, f"{path}.{key}", policy)
                for key, child in value.items()
            }
        if isinstance(value, list):
            element_path = f"{path}{ARRAY_MARKER}"
            return [self._value(element, element_path, policy) for element in value]
        return value

    def _key(self, key: str, path: str) -> str:
        if (self.collection, path, key) in self.schema or not self.guard.is_personal(key):
            return key
        self.replaced[f"{path}.{KEYS_PATH}"] += 1
        return fake_token(self._seed(key), len(key))

    def _seed(self, value: str) -> bytes:
        return hmac.new(self.key, value.encode(), hashlib.sha256).digest()

    def _string(self, value: str, path: str, rule: Rule | None) -> str:
        if isinstance(rule, frozenset):
            if value in rule:
                return value
            rule = None
        if rule is StringRule.IDENTIFIER and is_opaque_id(value):
            return value
        if rule is StringRule.KEEP:
            if not self.guard.is_personal(value):
                return value
            self.replaced[path] += 1
        seed = self._seed(value)
        if rule is StringRule.FAKE_EMAIL:
            return f"user-{seed[:8].hex()}@{FAKE_EMAIL_DOMAIN}"
        if rule is StringRule.IDENTIFIER or not any(char.isspace() for char in value):
            return fake_token(seed, len(value))
        return fake_words(seed, len(value))


def fake_token(seed: bytes, length: int) -> str:
    """Return a base-36 token of exactly length characters; distinct seeds give distinct tokens."""
    number = int.from_bytes(seed)
    chars: list[str] = []
    while len(chars) < length:
        if number == 0:
            seed = hashlib.sha256(seed).digest()
            number = int.from_bytes(seed)
        number, digit = divmod(number, len(TOKEN_ALPHABET))
        chars.append(TOKEN_ALPHABET[digit])
    return "".join(chars)


def fake_words(seed: bytes, length: int) -> str:
    """Return lorem words of exactly length characters, chosen by seed."""
    rng = random.Random(seed)
    parts: list[str] = []
    size = 0
    while size <= length:
        word = rng.choice(WORDS)
        parts.append(word)
        size += len(word) + 1
    return " ".join(parts)[:length]
