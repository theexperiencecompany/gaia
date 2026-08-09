"""GAIA-Bench suite: rank the GAIA agent on the official GAIA benchmark.

Runs the real GAIA validation set (``gaia-benchmark/GAIA``, 2023 validation:
165 rows = 53 L1 + 86 L2 + 26 L3) through the live dev executor endpoint and
scores exact-match with a bug-for-bug port of the official leaderboard scorer
(``huggingface.co/spaces/gaia-benchmark/leaderboard/blob/main/scorer.py``).

Dataset access
--------------
The GAIA dataset is gated. Loading it requires ``HF_TOKEN`` (an account that
accepted the dataset terms at https://huggingface.co/datasets/gaia-benchmark/GAIA).
Without it the suite falls back to 3 curated GAIA-style cases so the harness
stays testable offline; every case is tagged ``source:real`` or
``source:curated`` so reports can tell them apart. A previously downloaded
copy cached at ``data/gaia/metadata.parquet`` (gitignored) is reused without
a token. Reading parquet needs ``pyarrow`` (or the ``datasets`` library,
which is tried first) — see the loud message when either is missing.

Attachments
-----------
38 of the 165 rows carry attachments (xlsx/png/pdf/mp3/...). Each is delivered
one of three ways, and every case is tagged with which:

``attachment:uploaded``
    The file is POSTed to ``/api/v1/dev/attachments``, which runs the same
    ``FileService.upload`` the product's ``POST /api/v1/upload`` runs — real
    anydoc/pdf_inspector/vision extraction, real summary, real Mongo + ChromaDB
    index. The upload and the executor run share a ``conversation_id``, so
    ``prepare_executor_execution`` surfaces the file to the agent through the
    shipped path and ``search_uploaded_files`` reads the extracted content.
    Applies to every extension in ``UPLOAD_CONTENT_TYPES``.

``attachment:inlined``
    A harness shim, not the product's ingestion path: the file's text is pasted
    into the task (truncated to the endpoint's 20_000-char field). Reserved for
    the extensions the product's own uploader refuses (``INLINE_EXTS``) — these
    cases prove the agent can reason over the content, NOT that upload works.

skipped
    No ingestion path at all (audio, archives, ``.pdb``). The case gets
    ``expected["skip_reason"]`` naming the limitation, and the transport returns
    a failed CaseRun carrying it (core/runner.py has no native skip concept — it
    records any run with ``error`` set as ``failed``). ``load_cases`` prints the
    full denominator: total, runnable, and skipped counts per reason.

The dev endpoint exposes no tool-call trace and no token usage, so
``tool_calls`` is ``[]`` and token counts are estimates recorded in ``raw``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Coroutine
from dataclasses import dataclass
import os
from pathlib import Path
import re
import string
import sys
from typing import Any, ClassVar
import uuid
import warnings

import httpx
from opik.evaluation.metrics import base_metric, score_result
import pandas as pd

from app.constants.files import CSV_MIME, DOCX_MIME, PDF_MIME, PPTX_MIME, XLSX_MIME
from app.utils.upload_validation import ALLOWED_CONTENT_TYPES, MAX_UPLOAD_BYTES
from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.gates import SELF_SCORED, ExtraGates, validate_gates
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.types import Case, CaseRun

DATASET_REPO = "gaia-benchmark/GAIA"
METADATA_REPO_PATH = "2023/validation/metadata.parquet"
METADATA_URL = f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/main/{METADATA_REPO_PATH}"
GATE_NOTICE = (
    f"{DATASET_REPO} is gated: accept the terms at "
    f"https://huggingface.co/datasets/{DATASET_REPO} and export HF_TOKEN"
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "gaia"
ATTACH_DIR = DATA_DIR / "attachments"
METADATA_CACHE = DATA_DIR / "metadata.parquet"

DEV_API_BASE = os.environ.get("EVALS_DEV_API_BASE", "http://localhost:9460")

CONTRACT_LINE = (
    'Solve the task. Finish your reply with exactly "FINAL ANSWER: ..." '
    "where ... is a number or as few words as possible."
)
FINAL_ANSWER_RE = re.compile(r"\bfinal\s*answer\s*:\s*", re.IGNORECASE)
# The dev direct-run endpoint wraps narration-only responses (subagent never
# ran a tool) in an envelope built by app/agents/core/subagents/subagent_runner.py:
#   The <agent> subagent ended without running any tool — it only produced
#   planning text: "<message>". Re-issue the handoff with an explicit
#   instruction to perform the action.
# Unwrap it so the recorded text is exactly what the agent said.
DEV_WRAPPER_RE = re.compile(
    r"^The .+ subagent ended without running any tool — it only produced "
    r'planning text: "(.*)"\. Re-issue the handoff with an explicit '
    r"instruction to perform the action\.$",
    re.DOTALL,
)

TASK_FIELD_MAX = 20_000
ATTACH_BUDGET = 18_000
MIN_ATTACH_BUDGET = 500

# Content type the harness declares per attachment extension. A browser supplies
# this on a real upload; the harness has to. Office/PDF types come from the
# product's own constants, images are literals the allowlist has no constant for.
UPLOAD_CONTENT_TYPES: dict[str, str] = {
    ".csv": CSV_MIME,
    ".docx": DOCX_MIME,
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".json": "application/json",
    ".pdf": PDF_MIME,
    ".png": "image/png",
    ".pptx": PPTX_MIME,
    ".txt": "text/plain",
    ".xlsx": XLSX_MIME,
}

# Fail at import rather than 415 a fifth of the benchmark case-by-case if the
# product ever narrows its allowlist. upload_validation is the one authority.
_UNSHIPPED_TYPES = sorted(set(UPLOAD_CONTENT_TYPES.values()) - ALLOWED_CONTENT_TYPES)
if _UNSHIPPED_TYPES:
    raise RuntimeError(
        f"gaia_bench would upload content types the product rejects: {_UNSHIPPED_TYPES}. "
        "app/utils/upload_validation.py is the authority — fix UPLOAD_CONTENT_TYPES "
        "or restore the allowlist entry."
    )

# Extensions the product's uploader refuses — no allowlisted content type
# (.xml/.jsonld) or a filename extension it blocks outright (.py). Their text is
# pasted into the task instead. That is a HARNESS SHIM, not the shipped ingestion
# path, and cases using it are tagged so no report can present them as evidence
# that attachment upload works.
INLINE_EXTS = {".xml", ".jsonld", ".py"}

REQUIRED_COLUMNS = ("task_id", "Question", "Level", "Final answer")


# ---------------------------------------------------------------------------
# Official GAIA scorer — bug-for-bug port. Do NOT "improve" these functions.
# Semantics match huggingface.co/spaces/gaia-benchmark/leaderboard/scorer.py:
# is_float via float() try; normalize_number_str strips $, %, commas and
# returns float("inf") on failure; split_string splits on [,;]; normalize_str
# removes all whitespace, then (optionally) all punctuation, then lowercases.
# No article removal, no month normalization, no unicode normalization.
# ---------------------------------------------------------------------------


def is_float(element: str | int | float) -> bool:
    try:
        float(element)
        return True
    except ValueError:
        return False


def normalize_number_str(number_str: str) -> float:
    # we replace these common units and commas to allow
    # conversion to float
    for char in ["$", "%", ","]:
        number_str = number_str.replace(char, "")
    try:
        return float(number_str)
    except ValueError:
        print(f"String {number_str} cannot be normalized to number str.")
        return float("inf")


def split_string(s: str, char_list: tuple[str, ...] = (",", ";")) -> list[str]:
    pattern = f"[{''.join(char_list)}]"
    return re.split(pattern, s)


def normalize_str(input_str: str, remove_punct: bool = True) -> str:
    # Remove all white spaces. Required e.g for seagull vs. sea gull
    no_spaces = re.sub(r"\s", "", input_str)
    # Remove punctuation, if specified.
    if remove_punct:
        translator = str.maketrans("", "", string.punctuation)
        return no_spaces.lower().translate(translator)
    return no_spaces.lower()


def question_scorer(model_answer: str | None, ground_truth: str) -> bool:
    if model_answer is None:
        model_answer = "None"

    # if gt is a number
    if is_float(ground_truth):
        print(f"Evaluating {model_answer} as a number.")
        normalized_answer = normalize_number_str(model_answer)
        return normalized_answer == float(ground_truth)

    # if gt is a list
    if any(char in ground_truth for char in [",", ";"]):
        print(f"Evaluating {model_answer} as a comma separated list.")
        # question with the fish: normalization removes punct

        gt_elems = split_string(ground_truth)
        ma_elems = split_string(model_answer)

        # check length is the same
        if len(gt_elems) != len(ma_elems):
            warnings.warn(
                "Answer lists have different lengths, returning False.",
                UserWarning,
                stacklevel=2,
            )
            return False

        # compare each element as float or str
        comparisons: list[bool] = []
        for ma_elem, gt_elem in zip(ma_elems, gt_elems):
            if is_float(gt_elem):
                normalized_ma_elem = normalize_number_str(ma_elem)
                comparisons.append(normalized_ma_elem == float(gt_elem))
            else:
                # we do not remove punct since comparisons can include punct
                comparisons.append(
                    normalize_str(ma_elem, remove_punct=False)
                    == normalize_str(gt_elem, remove_punct=False)
                )
        return all(comparisons)

    # if gt is a str
    print(f"Evaluating {model_answer} as a string.")
    return normalize_str(model_answer) == normalize_str(ground_truth)


# ---------------------------------------------------------------------------
# Answer extraction (harness-side, not part of the official scorer).
# ---------------------------------------------------------------------------


def extract_final_answer(text: str) -> str:
    """Everything after the LAST \"FINAL ANSWER:\" marker, else the last line."""
    matches = list(FINAL_ANSWER_RE.finditer(text))
    if matches:
        return text[matches[-1].end() :].strip()
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


# ---------------------------------------------------------------------------
# Opik metric: the official exact-match scorer, deterministic (no judge).
# ---------------------------------------------------------------------------


def _last_assistant_text(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            content = message.get("content", "")
            if isinstance(content, str):
                return content
    return ""


class GaiaExactMetric(base_metric.BaseMetric):
    """Official GAIA question_scorer as a deterministic Opik metric."""

    def __init__(self) -> None:
        super().__init__("gaia_exact")

    def score(
        self,
        output: str,
        expected: object,
        messages: object = None,
        end_state: object = None,
        **ignored: object,
    ) -> score_result.ScoreResult:
        del ignored
        expected = expected if isinstance(expected, dict) else {}
        skip_reason = expected.get("skip_reason")
        if skip_reason:
            return score_result.ScoreResult(
                name=self.name,
                value=0.0,
                reason=f"skipped: {skip_reason}",
                metadata={"skipped": True},
            )
        gaia = expected.get("gaia", {})
        ground_truth = gaia.get("ground_truth") if isinstance(gaia, dict) else None
        if not isinstance(ground_truth, str):
            return score_result.ScoreResult(
                name=self.name,
                value=0.0,
                reason="no ground truth",
                scoring_failed=True,
            )
        # core's journal drops run.text, so finalize replays give output="";
        # fall back to the stored end_state / transcript.
        if output:
            model_answer = extract_final_answer(output)
        elif isinstance(end_state, dict) and isinstance(end_state.get("final_answer"), str):
            model_answer = end_state["final_answer"]
        else:
            model_answer = extract_final_answer(_last_assistant_text(messages))
        matched = question_scorer(model_answer, ground_truth)
        return score_result.ScoreResult(
            name=self.name,
            value=1.0 if matched else 0.0,
            reason=f"answer={model_answer!r} gt={ground_truth!r} -> {matched}",
        )


# ---------------------------------------------------------------------------
# Dataset loading.
# ---------------------------------------------------------------------------


def _as_str(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() in {"nan", "nat", "none"} else text


def _as_int(value: object) -> int:
    """A row's integer field, defended exactly like ``_as_str``.

    ``int()`` on a bare ``object`` is not something mypy accepts, and at runtime
    a row that omits the column gives ``None`` (TypeError) while parquet gives
    ``NaN`` for a missing numeric (ValueError). Either one aborted ``load_cases``
    for the whole suite over a single malformed row. 0 is outside GAIA's level
    range (1-3), so a defaulted value is visible as ``L0`` rather than silently
    passing for a real level.
    """
    text = _as_str(value)
    try:
        return int(float(text))
    except ValueError:
        return 0


def _read_parquet(path: Path) -> list[dict[str, object]]:
    try:
        import pyarrow as pa  # engine availability probe — pandas needs it for parquet
    except ImportError as exc:
        raise RuntimeError(
            "metadata.parquet needs pyarrow to be read: "
            "`uv add --group backend pyarrow` (or install the `datasets` package)."
        ) from exc
    del pa
    frame = pd.read_parquet(path, engine="pyarrow")
    return frame.to_dict(orient="records")


def _rows_from_datasets() -> list[dict[str, object]] | None:
    try:
        from datasets import load_dataset
    except ImportError:
        return None
    dataset = load_dataset(DATASET_REPO, "2023_all", split="validation")
    return [dict(row) for row in dataset]


def _download_metadata(token: str) -> list[dict[str, object]] | None:
    resp = httpx.get(
        METADATA_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120.0,
        follow_redirects=True,
    )
    if resp.status_code == 401:
        print(f"[gaia_bench] HF rejected the token (401) — {GATE_NOTICE}.")
        return None
    if resp.status_code != 200:
        print(
            f"[gaia_bench] metadata download failed: HTTP {resp.status_code} "
            f"({_body_snippet(resp)}) — falling back to curated cases."
        )
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_CACHE.write_bytes(resp.content)
    return _read_parquet(METADATA_CACHE)


def _load_dataset_rows() -> list[dict[str, object]] | None:
    """Real GAIA validation rows, or None when the dataset is unavailable.

    Order: cached parquet (offline, reproducible) -> ``datasets`` library ->
    direct parquet download with HF_TOKEN. Prints loud instructions on every
    failure path; a *present but unreadable* cache raises instead of silently
    running curated cases.
    """
    if METADATA_CACHE.exists():
        return _read_parquet(METADATA_CACHE)
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        print(
            f"[gaia_bench] HF_TOKEN is not set — {GATE_NOTICE}. "
            "Falling back to 3 curated GAIA-style cases so the suite stays "
            "testable; cases are tagged source:curated, never source:real."
        )
        return None
    rows = _rows_from_datasets()
    if rows is not None:
        return rows
    print("[gaia_bench] `datasets` package not installed — downloading metadata.parquet directly.")
    return _download_metadata(token)


def _validate_rows(rows: list[dict[str, object]]) -> None:
    missing = [col for col in REQUIRED_COLUMNS if not any(col in row for row in rows[:1])]
    if missing:
        raise RuntimeError(f"GAIA metadata missing required columns: {missing}")


# ---------------------------------------------------------------------------
# Case construction.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttachmentSpec:
    """A downloaded attachment and the multipart fields the upload needs."""

    path: Path
    filename: str
    content_type: str


@dataclass(frozen=True)
class AttachmentDelivery:
    """How one row's attachment reaches the agent — or why it cannot.

    Exactly one field is set: ``upload`` for the real ingestion path,
    ``inline_text`` for the harness shim, ``skip_reason`` when neither applies.
    """

    upload: AttachmentSpec | None = None
    inline_text: str | None = None
    skip_reason: str | None = None


def _download_attachment(file_path: str) -> Path | None:
    """Cache one attachment locally, or None with a loud reason when it can't be fetched."""
    target = ATTACH_DIR / Path(file_path).name
    if target.exists():
        return target
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        print(
            f"[gaia_bench] attachment {file_path} needs HF_TOKEN to download "
            f"({GATE_NOTICE}) — skipping this case."
        )
        return None
    url = f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/main/{file_path}"
    resp = httpx.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120.0,
        # Binary attachments are LFS-backed and resolve to a CDN redirect.
        follow_redirects=True,
    )
    if resp.status_code != 200:
        print(
            f"[gaia_bench] attachment {file_path} download failed: "
            f"HTTP {resp.status_code} — skipping this case."
        )
        return None
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(resp.content)
    return target


def _plan_attachment(file_path: str, file_name: str) -> AttachmentDelivery:
    """Decide how a row's attachment is delivered, downloading it if it can be."""
    suffix = Path(file_path).suffix.lower()
    content_type = UPLOAD_CONTENT_TYPES.get(suffix)
    if content_type is None and suffix not in INLINE_EXTS:
        return AttachmentDelivery(
            skip_reason=(
                f"no ingestion path for {suffix or 'extension-less'} attachments: the product's "
                "upload allowlist (app/utils/upload_validation.py) rejects the content type, "
                "and the file is not text the harness can inline"
            )
        )
    local = _download_attachment(file_path)
    if local is None:
        return AttachmentDelivery(
            skip_reason=f"attachment {file_path} could not be downloaded (see the message above)"
        )
    if content_type is None:
        return AttachmentDelivery(inline_text=local.read_text(encoding="utf-8", errors="replace"))
    size = local.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        return AttachmentDelivery(
            skip_reason=(
                f"attachment is {size} bytes, over the product's "
                f"{MAX_UPLOAD_BYTES}-byte upload limit"
            )
        )
    return AttachmentDelivery(
        upload=AttachmentSpec(path=local, filename=file_name, content_type=content_type)
    )


def _fresh_email() -> str:
    return f"gaia-{uuid.uuid4().hex}@evals.local"


def _real_case(row: dict[str, object], index: int) -> Case:
    task_id = _as_str(row.get("task_id")) or f"real-{index:03d}"
    question = _as_str(row.get("Question"))
    level = _as_int(row.get("Level"))
    ground_truth = _as_str(row.get("Final answer"))
    file_name = _as_str(row.get("file_name")) or None
    file_path = _as_str(row.get("file_path")) or None
    gaia: dict[str, object] = {
        "ground_truth": ground_truth,
        "task_id": task_id,
        "level": level,
        "file_path": file_path,
        "file_name": file_name,
    }
    expected: dict[str, object] = {
        "category": f"L{level}",
        "gaia": gaia,
        "score": {"gates": ["gaia_exact"]},
    }
    tags = ["gaia", f"level:L{level}", "source:real"]
    # Upload and executor run must share this id: prepare_executor_execution
    # reconstructs a conversation's uploads from the thread id alone.
    setup: dict[str, Any] = {"email": _fresh_email(), "conversation_id": uuid.uuid4().hex}
    prompt = question
    if file_path:
        display_name = file_name or Path(file_path).name
        delivery = _plan_attachment(file_path, display_name)
        attachment: dict[str, object] = {"file_name": file_name, "file_path": file_path}
        if delivery.skip_reason is not None:
            expected["skip_reason"] = delivery.skip_reason
            tags.append("skip")
        elif delivery.upload is not None:
            setup["attachment"] = delivery.upload
            tags.append("attachment:uploaded")
            attachment["delivery"] = "uploaded"
            attachment["content_type"] = delivery.upload.content_type
            gaia["attachment"] = attachment
        else:
            # inline_text — the harness shim; see INLINE_EXTS.
            text = delivery.inline_text or ""
            budget = max(ATTACH_BUDGET - len(CONTRACT_LINE) - len(question), 0)
            if budget < MIN_ATTACH_BUDGET:
                expected["skip_reason"] = (
                    f"attachment too large for dev endpoint task field ({TASK_FIELD_MAX} chars)"
                )
                tags.append("skip")
            else:
                content = text[:budget]
                truncated = len(text) > len(content)
                if truncated:
                    content = content + "\n...[attachment truncated]"
                prompt = f"{question}\n\n[Attachment: {display_name}]\n{content}\n[/Attachment]"
                tags.append("attachment:inlined")
                attachment["delivery"] = "inlined"
                attachment["truncated"] = truncated
                gaia["attachment"] = attachment
    return Case(
        id=f"gaia-{task_id}",
        ticket=f"GAIA {task_id} (L{level})",
        prompt=prompt,
        expected=expected,
        tags=tags,
        setup=setup,
    )


def _curated_cases() -> list[Case]:
    """Three hand-written GAIA-style cases used when the real dataset is unavailable."""
    specs = [
        (
            "gaia-curated-1",
            "Curated L1-style — pure recall, no web needed.",
            "How many letters are in the word 'supercalifragilisticexpialidocious'?",
            "34",
            1,
        ),
        (
            "gaia-curated-2",
            "Curated L2-style — arithmetic over a stated recipe.",
            (
                "A recipe calls for 1.5 cups of flour per batch and each batch yields "
                "12 cookies. How many cups of flour are needed to make exactly 40 cookies?"
            ),
            "5",
            2,
        ),
        (
            "gaia-curated-3",
            "Curated L3-style — needs a web lookup (the dev executor has web tools).",
            (
                "The Metropolitan line is the oldest line of the London Underground. "
                "In what year did the first underground section of the Metropolitan line open?"
            ),
            "1863",
            3,
        ),
    ]
    cases: list[Case] = []
    for case_id, ticket, question, ground_truth, level in specs:
        cases.append(
            Case(
                id=case_id,
                ticket=ticket,
                prompt=question,
                expected={
                    "category": f"L{level}",
                    "gaia": {
                        "ground_truth": ground_truth,
                        "task_id": case_id,
                        "level": level,
                        "file_path": None,
                        "file_name": None,
                    },
                    "score": {"gates": ["gaia_exact"]},
                },
                tags=["gaia", f"level:L{level}", "source:curated"],
                setup={"email": _fresh_email()},
            )
        )
    return cases


def _print_load_report(cases: list[Case]) -> None:
    """Print the full denominator: what runs, how attachments arrive, what is skipped and why.

    A skipped case must never vanish from the count — an accuracy quoted over a
    silently shrunk denominator is the defect this report exists to prevent.
    """
    skipped = [case for case in cases if "skip" in case.tags]
    uploaded = sum(1 for case in cases if "attachment:uploaded" in case.tags)
    inlined = sum(1 for case in cases if "attachment:inlined" in case.tags)
    print(
        f"[gaia_bench] {len(cases)} real GAIA validation cases: "
        f"{len(cases) - len(skipped)} runnable, {len(skipped)} skipped. "
        f"Attachments: {uploaded} uploaded through the product's ingestion path, "
        f"{inlined} inlined as text by the harness."
    )
    for reason, count in Counter(
        str(case.expected.get("skip_reason")) for case in skipped
    ).most_common():
        print(f"[gaia_bench]   skipped x{count}: {reason}")


def _interleave_by_level(cases: list[Case]) -> list[Case]:
    """Round-robin across levels so ``--limit N`` yields a stratified sample."""
    buckets: dict[str, list[Case]] = {}
    for case in cases:
        buckets.setdefault(str(case.expected.get("category", "?")), []).append(case)
    ordered: list[Case] = []
    keys = sorted(buckets)
    while any(buckets[key] for key in keys):
        for key in keys:
            if buckets[key]:
                ordered.append(buckets[key].pop(0))
    return ordered


# ---------------------------------------------------------------------------
# Transport: live dev executor endpoint (separate process, its own LLM lane).
# ---------------------------------------------------------------------------


def _body_snippet(resp: httpx.Response) -> str:
    return (resp.text or "")[:300]


class DevExecutorTransport:
    """POST /api/v1/dev/users then /api/v1/dev/executor, per fresh UUID email."""

    def __init__(self, dataset_available: bool) -> None:
        self.dataset_available = dataset_available

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker, provider
        skip_reason = case.expected.get("skip_reason")
        if skip_reason:
            return CaseRun(
                case_id=case.id,
                error=f"skipped: {skip_reason}",
            )
        if "source:real" in case.tags and not self.dataset_available:
            return CaseRun(
                case_id=case.id,
                error=(
                    f"real GAIA dataset unavailable — {GATE_NOTICE} (case is "
                    "source:real but only curated cases were loaded)"
                ),
            )
        email = str(case.setup.get("email") or _fresh_email())
        conversation_id = str(case.setup.get("conversation_id") or uuid.uuid4().hex)
        attachment = case.setup.get("attachment")
        if attachment is not None and not isinstance(attachment, AttachmentSpec):
            raise RuntimeError(
                f"{case.id}: setup['attachment'] must be an AttachmentSpec, got {type(attachment)}"
            )
        task = f"{CONTRACT_LINE}\n\n{case.prompt}"
        timeout = httpx.Timeout(600.0, connect=30.0)
        attachment_record: dict[str, Any] = {"kind": "attachment", "delivery": "none"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            await self._mint_user(client, email)
            if attachment is not None:
                attachment_record = await self._attach(client, email, conversation_id, attachment)
            elif "attachment:inlined" in case.tags:
                attachment_record = {"kind": "attachment", "delivery": "inlined"}
            payload = await self._run_executor(client, email, task, conversation_id)
        text = self._extract_message(payload)
        if not text:
            return CaseRun(case_id=case.id, error="executor returned an empty message")
        final_answer = extract_final_answer(text)
        tokens_in = estimate_tokens(task)
        tokens_out = estimate_tokens(text)
        return CaseRun(
            case_id=case.id,
            messages=[
                {"role": "user", "content": task},
                {"role": "assistant", "content": text},
            ],
            tool_calls=[],
            end_state={"final_answer": final_answer},
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            raw=[
                {
                    "kind": "usage",
                    "estimated": True,
                    "input_tokens": tokens_in,
                    "output_tokens": tokens_out,
                    "note": "dev endpoint exposes no token usage; estimated via core.cost.estimate_tokens",
                },
                {
                    "kind": "dev_executor",
                    "agent": payload.get("agent"),
                    "conversation_id": payload.get("conversation_id"),
                    "thread_id": payload.get("thread_id"),
                },
                attachment_record,
            ],
        )

    async def _mint_user(self, client: httpx.AsyncClient, email: str) -> None:
        resp = await client.post(f"{DEV_API_BASE}/api/v1/dev/users", json={"email": email})
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"dev users endpoint failed: HTTP {resp.status_code}: {_body_snippet(resp)}"
            )

    async def _attach(
        self,
        client: httpx.AsyncClient,
        email: str,
        conversation_id: str,
        attachment: AttachmentSpec,
    ) -> dict[str, Any]:
        """Ingest the case's file through the product's upload service.

        Raises on anything but a 201: an attachment that silently failed to
        ingest would let the agent answer from the question text alone and be
        scored as if it had read the file.
        """
        resp = await client.post(
            f"{DEV_API_BASE}/api/v1/dev/attachments",
            data={"email": email, "conversation_id": conversation_id},
            files={
                "file": (
                    attachment.filename,
                    attachment.path.read_bytes(),
                    attachment.content_type,
                )
            },
        )
        if resp.status_code != 201:
            raise RuntimeError(
                f"dev attachments endpoint failed for {attachment.filename}: "
                f"HTTP {resp.status_code}: {_body_snippet(resp)}"
            )
        document = resp.json()
        if not isinstance(document, dict):
            raise RuntimeError(f"dev attachments returned unexpected JSON: {document!r}")
        pages = document.get("page_wise_summary")
        return {
            "kind": "attachment",
            "delivery": "uploaded",
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "file_id": document.get("file_id"),
            "summary": document.get("description"),
            "extracted_pages": len(pages) if isinstance(pages, list) else None,
        }

    async def _run_executor(
        self, client: httpx.AsyncClient, email: str, task: str, conversation_id: str
    ) -> dict[str, object]:
        resp = await client.post(
            f"{DEV_API_BASE}/api/v1/dev/executor",
            json={"email": email, "task": task, "conversation_id": conversation_id},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"dev executor endpoint failed: HTTP {resp.status_code}: {_body_snippet(resp)}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"dev executor returned non-JSON: {_body_snippet(resp)}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"dev executor returned unexpected JSON: {payload!r}")
        return payload

    @staticmethod
    def _extract_message(payload: dict[str, object]) -> str:
        message = payload.get("message")
        if isinstance(message, str):
            return DevExecutorTransport._unwrap_wrapper(message)
        if isinstance(message, dict):
            for key in ("response", "text"):
                value = message.get(key)
                if isinstance(value, str):
                    return DevExecutorTransport._unwrap_wrapper(value)
        return ""

    @staticmethod
    def _unwrap_wrapper(text: str) -> str:
        match = DEV_WRAPPER_RE.match(text)
        return match.group(1) if match else text


# ---------------------------------------------------------------------------
# Suite.
# ---------------------------------------------------------------------------


@register_suite("gaia_bench")
class GaiaBenchSuite(Suite):
    name = "gaia_bench"
    project = "gaia-bench"
    label = "GAIA-Bench"

    #: Scored inside this suite's own ``score()`` from the transport's end
    #: state, not through the shared dispatcher — a benchmark verdict, not a
    #: reusable check. Declared so load-time validation knows the name is real.
    EXTRA_GATES: ClassVar[ExtraGates] = {"gaia_exact": SELF_SCORED}

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self._cases: list[Case] | None = None
        self._dataset_available = False
        self._transport: DevExecutorTransport | None = None

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        if self._cases is None:
            rows = _load_dataset_rows()
            if rows is None:
                self._cases = _curated_cases()
                self._dataset_available = False
            else:
                _validate_rows(rows)
                cases = [_real_case(row, index) for index, row in enumerate(rows)]
                _print_load_report(cases)
                self._cases = _interleave_by_level(cases)
                self._dataset_available = True
            for case in self._cases:
                validate_gates(self.name, case.id, case.gates, self.EXTRA_GATES)
        return self._cases

    def transport(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> Coroutine[None, None, CaseRun]:
        if self._transport is None:
            self._transport = DevExecutorTransport(self._dataset_available)
        return self._transport.run(case, cfg, tracker, provider)

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        if run.error or not run.end_state:
            return {}
        gaia = case.expected.get("gaia", {})
        ground_truth = gaia.get("ground_truth") if isinstance(gaia, dict) else None
        if not isinstance(ground_truth, str):
            return {}
        final_answer = run.end_state.get("final_answer")
        if not isinstance(final_answer, str):
            return {}
        matched = question_scorer(final_answer, ground_truth)
        return {"gaia_exact": 1.0 if matched else 0.0}

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        del cfg
        return [GaiaExactMetric()]


# ---------------------------------------------------------------------------
# Self-test: run `python -m scripts.evals.suites.gaia_bench` (no network).
# ---------------------------------------------------------------------------


def _skip_reason_names_the_allowlist(suffix: str) -> bool:
    """A skipped format must say it is a product limitation, and which one."""
    delivery = _plan_attachment(f"2023/validation/file{suffix}", f"file{suffix}")
    reason = delivery.skip_reason or ""
    return suffix in reason and "upload allowlist" in reason


def _run_self_test() -> int:
    checks: list[tuple[str, object, object]] = [
        ("list: identical '3,676' vs '3,676'", question_scorer("3,676", "3,676"), True),
        (
            "number: '3,676' vs '3676' (numeric GT strips the comma)",
            question_scorer("3,676", "3676"),
            True,
        ),
        ("number: '4.6%' vs '4.6'", question_scorer("4.6%", "4.6"), True),
        ("string: 'sea gull' vs 'seagull'", question_scorer("sea gull", "seagull"), True),
        ("number: '$89706.00' vs '89706.0'", question_scorer("$89706.00", "89706.0"), True),
        ("list: length mismatch 'a,b' vs 'a,b,c'", question_scorer("a,b", "a,b,c"), False),
        ("string: empty answer vs 'Paris'", question_scorer("", "Paris"), False),
        ("string: None answer vs 'Paris'", question_scorer(None, "Paris"), False),
        ("string: case-insensitive 'Paris' vs 'paris'", question_scorer("Paris", "paris"), True),
        (
            "string: punctuation stripped 'sea-gull!' vs 'seagull'",
            question_scorer("sea-gull!", "seagull"),
            True,
        ),
        ("number: '17' vs 17", question_scorer("17", "17"), True),
        (
            "list: case-insensitive 'John, Paul' vs 'john,paul' (remove_punct=False)",
            question_scorer("John, Paul", "john,paul"),
            True,
        ),
        (
            "extract: last marker inside executor wrapper prefix",
            extract_final_answer(
                DevExecutorTransport._unwrap_wrapper(
                    "The executor_agent subagent ended without running any tool — it "
                    'only produced planning text: "The capital of France is Paris.\n\n'
                    'FINAL ANSWER: Paris". Re-issue the handoff with an explicit '
                    "instruction to perform the action."
                )
            ),
            "Paris",
        ),
        (
            "extract: unwrap leaves plain text untouched",
            DevExecutorTransport._unwrap_wrapper("plain reply"),
            "plain reply",
        ),
        (
            "extract: plain marker",
            extract_final_answer("I searched the web.\n\nFINAL ANSWER: 42"),
            "42",
        ),
        (
            "extract: case-insensitive marker",
            extract_final_answer("The answer is\nfinal answer: 7"),
            "7",
        ),
        ("extract: no marker -> last line", extract_final_answer("Line one\nLine two"), "Line two"),
        ("extract: empty text", extract_final_answer(""), ""),
        # Attachment routing. Every extension must resolve to exactly one
        # delivery: a second route for the same format is a second way to do one
        # thing, and it hides which path a result actually came from.
        (
            "attachments: no extension is both uploadable and inlineable",
            sorted(set(UPLOAD_CONTENT_TYPES) & INLINE_EXTS),
            [],
        ),
        (
            "attachments: every declared content type is on the shipped allowlist",
            sorted(set(UPLOAD_CONTENT_TYPES.values()) - ALLOWED_CONTENT_TYPES),
            [],
        ),
        (
            "attachments: the formats GAIA carries route to the real upload path",
            sorted(
                {".xlsx", ".png", ".jpg", ".pdf", ".docx", ".pptx", ".csv", ".txt"}
                - set(UPLOAD_CONTENT_TYPES)
            ),
            [],
        ),
        # Unsupported formats are classified before any download, so these need
        # no network and no HF_TOKEN.
        (
            "attachments: .zip is skipped, naming the product limitation",
            _skip_reason_names_the_allowlist(".zip"),
            True,
        ),
        (
            "attachments: .mp3 is skipped, naming the product limitation",
            _skip_reason_names_the_allowlist(".mp3"),
            True,
        ),
        (
            "attachments: .pdb is skipped, naming the product limitation",
            _skip_reason_names_the_allowlist(".pdb"),
            True,
        ),
    ]

    rows = _load_dataset_rows()
    if rows is not None:
        checked = 0
        for row in rows:
            if checked >= 3:
                break
            ground_truth = _as_str(row.get("Final answer"))
            task_id = _as_str(row.get("task_id")) or "?"
            if not ground_truth:
                continue
            checks.append(
                (
                    f"real pair {task_id}: ground truth matches itself",
                    question_scorer(ground_truth, ground_truth),
                    True,
                )
            )
            checked += 1
        if checked == 0:
            print("  - real-dataset pair checks: no usable rows loaded")
    else:
        print(
            "  - real-dataset pair checks SKIPPED (dataset unavailable — set "
            "HF_TOKEN to load the real GAIA validation set)"
        )

    failures = 0
    for label, got, want in checks:
        if got == want:
            print(f"  PASS  {label}")
        else:
            print(f"  FAIL  {label}: got {got!r}, want {want!r}")
            failures += 1
    print(f"\ngaia_bench self-test: {len(checks) - failures}/{len(checks)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(_run_self_test())
