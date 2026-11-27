"""Flag any kept string or object key that looks like personal data, before it is written.

Every other string is overwritten, so kept values and keys are the whole leak surface. The
caller replaces a flagged value; nothing here records or prints the value itself.
"""

from dataclasses import dataclass, field
import re

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

SPACY_MODEL = "en_core_web_sm"
ENTITIES = (
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "PERSON",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "US_SSN",
)
MIN_SCORE = 0.6
#: Whole-value formats that are provably not free text: random-token ids and hex colours.
OPAQUE_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|[0-9a-f]{12,}"
    r"|[a-z]{1,12}_[0-9a-f]{8,}"
    r"|(?=[A-Za-z0-9]*[0-9])(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{16,}"
    r"|#[0-9a-fA-F]{6}"
)


def is_opaque_id(value: str) -> bool:
    return OPAQUE_ID.fullmatch(value) is not None


def _engine() -> AnalyzerEngine:
    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
        }
    )
    return AnalyzerEngine(nlp_engine=provider.create_engine())


@dataclass
class PiiGuard:
    """Judges each distinct value once and remembers the verdict."""

    engine: AnalyzerEngine = field(default_factory=_engine)
    verdicts: dict[str, bool] = field(default_factory=dict)

    def is_personal(self, value: str) -> bool:
        if is_opaque_id(value):
            return False
        verdict = self.verdicts.get(value)
        if verdict is None:
            hits = self.engine.analyze(value, entities=list(ENTITIES), language="en")
            verdict = any(hit.score >= MIN_SCORE for hit in hits)
            self.verdicts[value] = verdict
        return verdict
