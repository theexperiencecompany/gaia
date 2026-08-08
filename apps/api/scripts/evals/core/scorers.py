"""Deterministic Opik scorers for agent behavior.

Each is an ``opik`` BaseMetric so it works both in ``evaluate()`` at
finalize-time and standalone. Score kwargs are matched against the flattened
dataset-item keys ∪ task-output keys (opik semantics) — the bags are typed
``object`` because opik injects them dynamically; each scorer validates at
its boundary (app/CLAUDE.md rule 8).

Task outputs produced by the replay/run layer:
- ``output``     — final assistant text
- ``messages``   — [{role, content}] transcript
- ``tool_calls`` — [{name, args}] executed tool calls
- ``end_state``  — suite-provided world state after the run (e.g. todo rows)
"""

from __future__ import annotations

import json
import os
import re
from typing import cast

from opik.evaluation.metrics import base_metric, score_result


def _expected_of(expected: object) -> dict[str, object]:
    return cast(dict[str, object], expected) if isinstance(expected, dict) else {}


def _agent_text(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    return "\n".join(
        str(m.get("content", ""))
        for m in messages
        if isinstance(m, dict) and m.get("role") == "assistant"
    )


def _tool_calls_of(tool_calls: object) -> list[dict[str, object]]:
    if not isinstance(tool_calls, list):
        return []
    return [t for t in tool_calls if isinstance(t, dict)]


def _messages_of(messages: object) -> list[dict[str, object]]:
    if not isinstance(messages, list):
        return []
    return [m for m in messages if isinstance(m, dict)]


class ToolCallCorrectness(base_metric.BaseMetric):
    """Every expected tool call happened (with arg check per expected entry)."""

    def __init__(self) -> None:
        super().__init__("tool_call_correctness")

    def score(
        self,
        output: str,
        tool_calls: object = None,
        expected: object = None,
        **_ignored: object,
    ) -> score_result.ScoreResult:
        del output
        expected = _expected_of(expected)
        wanted = expected.get("tool_calls", [])
        actual = _tool_calls_of(tool_calls)
        if not wanted:
            return score_result.ScoreResult(
                name=self.name, value=1.0, reason="no tool calls expected"
            )
        missing: list[str] = []
        for want in wanted:
            if not isinstance(want, dict):
                continue
            name = str(want.get("tool", ""))
            min_calls = int(want.get("min_calls", 1))
            matches = [t for t in actual if t.get("name") == name]
            if len(matches) < min_calls:
                missing.append(f"{name} (called {len(matches)}/{min_calls})")
        if missing:
            return score_result.ScoreResult(
                name=self.name,
                value=0.0,
                reason=f"missing tool calls: {', '.join(missing)}",
            )
        return score_result.ScoreResult(
            name=self.name, value=1.0, reason="all expected tool calls seen"
        )


class EndStateEquality(base_metric.BaseMetric):
    """The world changed as the ground truth demands (τ-bench end-state gate)."""

    def __init__(self) -> None:
        super().__init__("end_state")

    def score(
        self,
        output: str,
        end_state: object = None,
        expected: object = None,
        **_ignored: object,
    ) -> score_result.ScoreResult:
        del output
        expected = _expected_of(expected)
        wanted = expected.get("end_state", {})
        if not wanted:
            return score_result.ScoreResult(
                name=self.name, value=1.0, reason="no end state expected"
            )
        actual = cast(dict[str, object], end_state) if isinstance(end_state, dict) else {}
        mismatches: list[str] = []
        for key, want in wanted.items():
            got = actual.get(str(key))
            if isinstance(want, list):
                if not isinstance(got, list) or not _list_contains_all(got, want):
                    mismatches.append(f"{key}: expected {want}, got {got}")
            elif got != want:
                mismatches.append(f"{key}: expected {want}, got {got}")
        if mismatches:
            return score_result.ScoreResult(name=self.name, value=0.0, reason="; ".join(mismatches))
        return score_result.ScoreResult(name=self.name, value=1.0, reason="end state matches")


def _list_contains_all(got: list[object], want: list[object]) -> bool:
    if not want:
        return True
    if len(got) < len(want):
        return False
    want_norm = [json.dumps(w, sort_keys=True, default=str) for w in want]
    got_norm = [json.dumps(g, sort_keys=True, default=str) for g in got]
    return all(w in got_norm for w in want_norm)


class CommunicateGate(base_metric.BaseMetric):
    """Every required string was actually relayed to the user."""

    def __init__(self) -> None:
        super().__init__("communicate")

    def score(
        self,
        output: str,
        messages: object = None,
        expected: object = None,
        **_ignored: object,
    ) -> score_result.ScoreResult:
        expected = _expected_of(expected)
        required = expected.get("communicate", [])
        if not required:
            return score_result.ScoreResult(name=self.name, value=1.0, reason="nothing required")
        text = _agent_text(messages) if messages else output
        lowered = text.lower()
        missing = [str(req) for req in required if str(req).lower() not in lowered]
        if missing:
            return score_result.ScoreResult(
                name=self.name, value=0.0, reason=f"never communicated: {missing}"
            )
        return score_result.ScoreResult(
            name=self.name, value=1.0, reason="all required info relayed"
        )


class BubbleBoundary(base_metric.BaseMetric):
    """Every assistant message is a distinct, non-empty, non-duplicated bubble."""

    def __init__(self) -> None:
        super().__init__("bubble_boundary")

    def score(self, messages: object = None, **_ignored: object) -> score_result.ScoreResult:
        msgs = _messages_of(messages)
        if not msgs:
            return score_result.ScoreResult(name=self.name, value=0.0, reason="no transcript")
        issues: list[str] = []
        prev: str | None = None
        for m in msgs:
            if m.get("role") != "assistant":
                continue
            content = str(m.get("content") or "").strip()
            if not content:
                issues.append("empty assistant bubble")
            if content == prev:
                issues.append("duplicate consecutive bubble")
            prev = content
        if issues:
            return score_result.ScoreResult(name=self.name, value=0.0, reason="; ".join(issues[:3]))
        return score_result.ScoreResult(
            name=self.name, value=1.0, reason="bubbles distinct and non-empty"
        )


class ToolCard(base_metric.BaseMetric):
    """Every tool call produced a valid card entry (name present, args parse)."""

    def __init__(self) -> None:
        super().__init__("tool_card")

    def score(self, tool_calls: object = None, **_ignored: object) -> score_result.ScoreResult:
        actual = _tool_calls_of(tool_calls)
        if not actual:
            return score_result.ScoreResult(
                name=self.name, value=1.0, reason="no tool calls to card"
            )
        issues: list[str] = []
        for t in actual:
            if not t.get("name"):
                issues.append("tool call without name")
            args = t.get("args", {})
            if args and not isinstance(args, dict):
                issues.append(f"{t.get('name')}: args not a dict")
        if issues:
            return score_result.ScoreResult(name=self.name, value=0.0, reason="; ".join(issues[:3]))
        return score_result.ScoreResult(name=self.name, value=1.0, reason="all tool calls carded")


class Suggestion(base_metric.BaseMetric):
    """Follow-up suggestions present (when expected), 3-4 items, short.

    The surface-level check lives here (fences/schema). Suites that stream the
    real SSE frames override this with the deep check (follow_up_actions event
    counts and lengths).
    """

    def __init__(self) -> None:
        super().__init__("suggestion")

    def score(
        self, messages: object = None, expected: object = None, **_ignored: object
    ) -> score_result.ScoreResult:
        expected = _expected_of(expected)
        if not expected.get("suggestions"):
            return score_result.ScoreResult(
                name=self.name, value=1.0, reason="no suggestions expected"
            )
        msgs = _messages_of(messages)
        if not msgs:
            return score_result.ScoreResult(name=self.name, value=0.0, reason="no transcript")
        last = next(
            (str(m.get("content", "")) for m in reversed(msgs) if m.get("role") == "assistant"), ""
        )
        if not last:
            return score_result.ScoreResult(name=self.name, value=0.0, reason="no assistant bubble")
        return score_result.ScoreResult(
            name=self.name,
            value=1.0,
            reason="suggestion surface present (deep check in quality suite)",
        )


class OpenUICheck(base_metric.BaseMetric):
    """OpenUI fences present (when expected) and structurally balanced."""

    def __init__(self) -> None:
        super().__init__("openui")

    def score(
        self, output: str, expected: object = None, **_ignored: object
    ) -> score_result.ScoreResult:
        expected = _expected_of(expected)
        want = bool(expected.get("openui"))
        fences = re.findall(r":::openui(.*?):::", output, flags=re.DOTALL)
        if want and not fences:
            return score_result.ScoreResult(
                name=self.name, value=0.0, reason="expected OpenUI, none emitted"
            )
        if not want:
            return score_result.ScoreResult(name=self.name, value=1.0, reason="not expected")
        bad = [f for f in fences if not f.strip().startswith("{")]
        if bad:
            return score_result.ScoreResult(
                name=self.name, value=0.0, reason="unparseable OpenUI fence"
            )
        return score_result.ScoreResult(
            name=self.name, value=1.0, reason=f"{len(fences)} OpenUI fence(s)"
        )


_RUBRIC_SYSTEM = """You are an evaluation judge for a personal AI assistant. You grade one
criterion at a time. For each criterion, respond with exactly:
CRITERION: <name>
VERDICT: <1|2|3|4|5>
REASON: <one sentence>
1 = completely fails the criterion, 5 = fully satisfies it.
Judge the ASSISTANT'S responses, never the user's messages. If the assistant's
text is empty or off-topic, give 1. Only the final CRITERION/VERDICT/REASON
block counts — anything earlier is deliberation."""


class RubricJudge(base_metric.BaseMetric):
    """LLM judge over per-case rubric criteria (GEval-style, rubric-led).

    Judge model comes from the harness config (default: Nous DeepSeek V4
    Flash) — deliberately a different family than any agent model.
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        super().__init__("rubric_judge")
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def score(
        self,
        output: str,
        expected: object = None,
        messages: object = None,
        **_ignored: object,
    ) -> score_result.ScoreResult:
        from litellm import completion

        expected = _expected_of(expected)
        criteria = expected.get("judge", {}).get("criteria", [])
        if not criteria:
            return score_result.ScoreResult(name=self.name, value=1.0, reason="no judge criteria")
        transcript = (
            "\n".join(
                f"{m.get('role', '?')}: {m.get('content', '')}" for m in _messages_of(messages)
            )
            if messages
            else output
        )
        user_prompt = (
            f"ASSISTANT RESPONSE:\n{output}\n\nFULL TRANSCRIPT:\n{transcript}\n\n"
            f"CRITERIA (grade each):\n" + "\n".join(f"- {c}" for c in criteria)
        )
        response = completion(
            model=f"openai/{self.model}",
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=0,
            messages=[
                {"role": "system", "content": _RUBRIC_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        verdict = response.choices[0].message.content or ""
        scores: list[int] = []
        for match in re.finditer(r"VERDICT:\s*([1-5])", verdict):
            scores.append(int(match.group(1)))
        if not scores:
            return score_result.ScoreResult(
                name=self.name,
                value=0.0,
                reason=f"judge returned no verdict: {verdict[:200]}",
                scoring_failed=True,
            )
        mean = sum(scores) / len(scores) / 5.0
        return score_result.ScoreResult(
            name=self.name,
            value=round(mean, 3),
            reason=f"criteria={len(scores)} mean={mean * 5:.1f}/5",
            metadata={"verdicts": scores, "criteria": criteria, "judge": self.model},
        )


class ProviderQuality(base_metric.BaseMetric):
    """Surfaces provider/model per case in Opik experiments (score value 1.0,
    the reason column carries the lane so the UI is glanceable)."""

    def __init__(self) -> None:
        super().__init__("provider")

    def score(
        self,
        output: str,
        provider: object = None,
        model: object = None,
        **_ignored: object,
    ) -> score_result.ScoreResult:
        del output
        return score_result.ScoreResult(
            name=self.name,
            value=1.0,
            reason=f"{provider}/{model}",
            metadata={"provider": str(provider), "model": str(model)},
        )


def judge_env(base_url_env: str, api_key_env: str) -> None:
    """Point LiteLLM's openai/ lane at the judge provider for this process."""
    os.environ["OPENAI_BASE_URL"] = os.environ[base_url_env]
    os.environ["OPENAI_API_KEY"] = os.environ[api_key_env]
