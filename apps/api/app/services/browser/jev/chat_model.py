"""Jev as the Browser-Use agent's decision model.

Browser-Use asks its chat model for an AgentOutput every step; this class
answers by having Jev decide the operation and target from the current page
state instead of returning a completion, and using the small text model only
to write a typed value when the decision needs one. Everything downstream
(execution, step cards, takeover, history, replay) is unchanged; calls that
are not a step decision go straight to the text model.
"""

from __future__ import annotations

from dataclasses import replace
import json
import re
from typing import TYPE_CHECKING, TypeVar, get_args, overload

from pydantic import BaseModel
from pydantic_core import CoreSchema, core_schema

from app.config.settings import settings
from app.constants.browser import (
    JEV_TEXT_HELPER_RECENT_ACTIONS,
    JEV_TEXT_VALUE_MAX_CHARS,
    BrowserHandoffAction,
    JevOperation,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.jev.gateway import JevGatewayClient, JevGatewayError
from app.services.browser.jev.live_values import read_live_values
from app.services.browser.jev.observation import JevElement, JevObservation, observe
from app.services.browser.jev.policy import (
    JevDecision,
    JevDecisionError,
    JevHistoryEntry,
    choose,
)
from app.services.browser.jev.prompts import (
    CAPTCHA_CHALLENGE,
    DONE_SUMMARY,
    TAKEOVER_REASON,
    TEXT_VALUE,
    URL_VALUE,
)
from app.services.browser.jev.viewport import ViewportBox, read_viewport
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession
    from browser_use.llm.base import BaseChatModel
    from browser_use.llm.messages import BaseMessage
    from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar("T", bound=BaseModel)

# Browser-Use action name → the Jev operations it makes available. Text entry
# is `input` in Browser-Use 0.11 and `input_text` before it; both are known.
_OPERATIONS_BY_ACTION: dict[str, tuple[JevOperation, ...]] = {
    "click": (JevOperation.CLICK,),
    "input": (JevOperation.TYPE_TEXT,),
    "input_text": (JevOperation.TYPE_TEXT,),
    "select_dropdown": (JevOperation.SELECT,),
    "scroll": (JevOperation.SCROLL_UP, JevOperation.SCROLL_DOWN),
    "wait": (JevOperation.WAIT,),
    "navigate": (JevOperation.NAVIGATE,),
    "go_back": (JevOperation.GO_BACK,),
    BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER: (JevOperation.REQUEST_HUMAN,),
    BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP: (JevOperation.SOLVE_CAPTCHA,),
    "done": (JevOperation.DONE, JevOperation.BLOCKED),
}
_BLOCKED_SUMMARY = "Could not make progress: no supported action can advance the task on this page."
_DEFAULT_TAKEOVER_REASON = "Complete this step in the live browser"
_DEFAULT_CAPTCHA_CHALLENGE = "Solve the CAPTCHA, then continue"
_USER_REQUEST = re.compile(r"<user_request>\s*(.*?)\s*</user_request>", re.DOTALL)


class _TextValue(BaseModel):
    text: str | None = None


class _TakeoverReason(BaseModel):
    text: str | None = None
    category: str = SensitiveCategory.IRREVERSIBLE.value


class JevChatModel:
    """Browser-Use BaseChatModel whose step decisions come from Jev."""

    _verified_api_keys = True

    def __init__(self, *, client: JevGatewayClient, text_model: BaseChatModel) -> None:
        self.model = client.model
        self.text_model = text_model
        self._client = client
        self._browser: BrowserSession | None = None
        self._task: str | None = None
        self._history: list[JevHistoryEntry] = []
        self._last_fingerprint: str | None = None
        self._steps = 0
        self._viewport: dict[int, ViewportBox] = {}

    def viewport_points(self) -> dict[int, tuple[float, float]]:
        """Return the last observation's on-screen centres by Browser-Use index, for the UI pulse."""
        return {
            index: (round(box.cx, 4), round(box.cy, 4))
            for index, box in self._viewport.items()
            if box.on_screen
        }

    @property
    def provider(self) -> str:
        return "vercel-ai-gateway"

    @property
    def name(self) -> str:
        return self.model

    @property
    def model_name(self) -> str:
        return self.model

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: type, handler: object) -> CoreSchema:
        # Browser-Use stores its model in pydantic settings; the Protocol asks for this.
        return core_schema.any_schema()

    def bind(self, browser: BrowserSession, task: str) -> None:
        """Give the policy the session whose observations it decides on, and the raw goal."""
        self._browser = browser
        self._task = task

    @overload
    async def ainvoke(
        self, messages: list[BaseMessage], output_format: None = None, **kwargs: object
    ) -> ChatInvokeCompletion[str]: ...

    @overload
    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T], **kwargs: object
    ) -> ChatInvokeCompletion[T]: ...

    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: object
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        if output_format is None or not _is_agent_output(output_format):
            return await self.text_model.ainvoke(messages, output_format, **kwargs)
        return await self._decide(messages, output_format)

    async def _decide(
        self, messages: list[BaseMessage], output_format: type[T]
    ) -> ChatInvokeCompletion[T]:
        from browser_use.llm.views import (  # noqa: PLC0415 -- heavy optional dep
            ChatInvokeCompletion,
            ChatInvokeUsage,
        )

        if self._browser is None:
            raise BrowserUnavailableError("Jev policy has no browser session bound.")
        state = await self._browser.get_browser_state_summary(cached=True, include_screenshot=False)
        selector_map = getattr(getattr(state, "dom_state", None), "selector_map", None) or {}
        self._viewport = await read_viewport(self._browser, selector_map)
        observation = observe(state, await read_live_values(self._browser), self._viewport)
        self._settle_previous_step(observation)
        goal = self._effective_goal(messages)
        registered = _registered_actions(output_format)
        offered = _offered_operations(registered)
        self._steps += 1

        try:
            decision = await choose(self._client, observation, goal, self._history, offered)
        except JevDecisionError as exc:
            # Nothing executes on a malformed answer; a WAIT keeps the loop honest
            # and the failure shows up in Jev's next recent_actions. On the step
            # Browser-Use narrows to `done` only, the honest answer is a failed done.
            log.warning(f"{LogTag.BROWSER} Jev decision rejected", error_type=type(exc).__name__)
            self._remember("WAIT", "error", str(exc))
            fallback = _idle_action(output_format)
            return ChatInvokeCompletion(
                completion=_output(output_format, fallback, next(iter(fallback)).upper(), str(exc)),
                usage=None,
            )

        action, text = await self._action_for(decision, observation, goal, registered)
        kind = (
            "error"
            if action.get("wait") and decision.operation is not JevOperation.WAIT
            else (decision.operation.value.lower())
        )
        self._remember(decision.label, kind, text)
        log.info(
            f"{LogTag.BROWSER} Jev step decided",
            step=self._steps,
            operation=decision.operation.value,
            target=decision.target,
            confidence=round(decision.confidence, 3),
            latency_ms=decision.evaluation.latency_ms if decision.evaluation else None,
        )
        usage = decision.evaluation.usage if decision.evaluation else None
        return ChatInvokeCompletion(
            completion=_output(
                output_format,
                action,
                decision.label,
                f"Step {self._steps}: {decision.label} (p={decision.confidence:.2f})",
            ),
            usage=ChatInvokeUsage(
                prompt_tokens=usage.input_tokens,
                prompt_cached_tokens=None,
                prompt_cache_creation_tokens=None,
                prompt_image_tokens=None,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.input_tokens + usage.output_tokens,
            )
            if usage
            else None,
        )

    async def _action_for(
        self, decision: JevDecision, observation: JevObservation, goal: str, registered: set[str]
    ) -> tuple[dict[str, dict[str, object]], str | None]:
        """Return the Browser-Use action a decision executes as, plus any text the helper wrote."""
        action: tuple[dict[str, dict[str, object]], str | None] | None = None
        match decision.operation:
            case JevOperation.DONE | JevOperation.BLOCKED:
                action = await self._terminal_action(decision, observation, goal)
            case JevOperation.REQUEST_HUMAN | JevOperation.SOLVE_CAPTCHA:
                action = await self._handoff_action(decision, observation, goal)
            case JevOperation.CLICK | JevOperation.TYPE_TEXT | JevOperation.SELECT:
                action = await self._element_action(decision, observation, goal, registered)
            case (
                JevOperation.SCROLL_UP
                | JevOperation.SCROLL_DOWN
                | JevOperation.WAIT
                | JevOperation.GO_BACK
                | JevOperation.NAVIGATE
            ):
                action = await self._control_action(decision, observation, goal)
        if action is None:
            raise JevDecisionError(f"Jev chose {decision.operation.value} without a usable target.")
        return action

    async def _terminal_action(
        self, decision: JevDecision, observation: JevObservation, goal: str
    ) -> tuple[dict[str, dict[str, object]], str | None]:
        if decision.operation is JevOperation.BLOCKED:
            return {"done": {"text": _BLOCKED_SUMMARY, "success": False}}, None
        summary = await self._field_text(DONE_SUMMARY, goal, observation, None)
        return {"done": {"text": summary or "Completed the task.", "success": True}}, summary

    async def _handoff_action(
        self, decision: JevDecision, observation: JevObservation, goal: str
    ) -> tuple[dict[str, dict[str, object]], str | None]:
        if decision.operation is JevOperation.SOLVE_CAPTCHA:
            challenge = await self._field_text(CAPTCHA_CHALLENGE, goal, observation, None)
            text = challenge or _DEFAULT_CAPTCHA_CHALLENGE
            return {BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP: {"challenge": text}}, text
        reason = await self._structured(_TakeoverReason, TAKEOVER_REASON, goal, observation, None)
        text = (reason.text if reason else None) or _DEFAULT_TAKEOVER_REASON
        category = reason.category if reason else SensitiveCategory.IRREVERSIBLE.value
        return _takeover(text, category), text

    async def _element_action(
        self, decision: JevDecision, observation: JevObservation, goal: str, registered: set[str]
    ) -> tuple[dict[str, dict[str, object]], str | None] | None:
        """None when the decision named no usable element, which the caller rejects."""
        element = decision.element
        if element is None:
            return None
        match decision.operation:
            case JevOperation.CLICK:
                return {"click": {"index": element.browser_index}}, None
            case JevOperation.TYPE_TEXT:
                value = await self._field_text(TEXT_VALUE, goal, observation, element)
                if value is None:
                    # A value the goal did not supply is never invented; the human
                    # supplies it instead, per the takeover policy.
                    return _takeover(f"Enter the {element.label}"[:80]), None
                input_action = "input" if "input" in registered else "input_text"
                return {
                    input_action: {"index": element.browser_index, "text": value, "clear": True}
                }, value
            case JevOperation.SELECT if decision.option is not None:
                return {
                    "select_dropdown": {
                        "index": element.browser_index,
                        "text": decision.option.label,
                    }
                }, decision.option.label
        return None

    async def _control_action(
        self, decision: JevDecision, observation: JevObservation, goal: str
    ) -> tuple[dict[str, dict[str, object]], str | None] | None:
        """None when the operation is not one of the controls, which the caller rejects."""
        match decision.operation:
            case JevOperation.SCROLL_UP:
                return {"scroll": {"down": False, "pages": 1.0}}, None
            case JevOperation.SCROLL_DOWN:
                return {"scroll": {"down": True, "pages": 1.0}}, None
            case JevOperation.WAIT:
                return {"wait": {"seconds": 1}}, None
            case JevOperation.GO_BACK:
                return {"go_back": {}}, None
            case JevOperation.NAVIGATE:
                url = await self._field_text(URL_VALUE, goal, observation, None)
                if not url or not url.lower().startswith(("http://", "https://")):
                    return {
                        "wait": {"seconds": 1}
                    }, "NAVIGATE needs a URL the goal implies; none found"
                return {"navigate": {"url": url, "new_tab": False}}, url
        return None

    async def _field_text(
        self, instructions: str, goal: str, observation: JevObservation, field: JevElement | None
    ) -> str | None:
        answer = await self._structured(_TextValue, instructions, goal, observation, field)
        value = answer.text if answer else None
        if not value or not value.strip() or len(value) > JEV_TEXT_VALUE_MAX_CHARS:
            return None
        return value

    async def _structured(
        self,
        output: type[T],
        instructions: str,
        goal: str,
        observation: JevObservation,
        field: JevElement | None,
    ) -> T | None:
        """Goal, field, page and recent actions in; one small JSON value out."""
        from browser_use.llm.messages import (  # noqa: PLC0415 -- heavy optional dep
            SystemMessage,
            UserMessage,
        )

        context = {
            "goal": goal,
            "field": {"label": field.label, "role": field.role, "value": field.value}
            if field
            else None,
            "page": {"title": observation.title, "url": observation.url, "text": observation.text},
            "recent_actions": [
                {"action": h.action, "text": h.text}
                for h in self._history[-JEV_TEXT_HELPER_RECENT_ACTIONS:]
            ],
            "user_note": self._latest_note(),
        }
        try:
            result = await self.text_model.ainvoke(
                [SystemMessage(content=instructions), UserMessage(content=json.dumps(context))],
                output,
            )
        except Exception as exc:
            log.warning(f"{LogTag.BROWSER} Jev text helper failed", error_type=type(exc).__name__)
            return None
        return result.completion

    def note_from_user(self, note: str | None) -> None:
        """Attach what the user said when handing the browser back to the step that asked.

        The takeover step is the last history entry: _remember runs inside
        _decide, before Browser-Use executes the action that blocks on the human.
        """
        if not self._history:
            raise RuntimeError("No step to attach a note to")
        self._history[-1] = replace(self._history[-1], note=note)

    def _settle_previous_step(self, observation: JevObservation) -> None:
        if self._history and self._last_fingerprint is not None:
            # replace(), not a rebuild: a note attached to this step must survive.
            self._history[-1] = replace(
                self._history[-1],
                page_changed=observation.fingerprint != self._last_fingerprint,
            )
        self._last_fingerprint = observation.fingerprint

    def _effective_goal(self, messages: list[BaseMessage]) -> str:
        """Return the task, plus the latest takeover note, which overrides it.

        Jev classifies against this goal, so a note left only in recent_actions
        never changed what DONE is measured against.
        """
        goal = self._task or _goal_from_messages(messages)
        note = self._latest_note()
        return f"{goal}\nThe user then said: {note}" if note else goal

    def _latest_note(self) -> str | None:
        return next((h.note for h in reversed(self._history) if h.note), None)

    def _remember(self, action: str, kind: str, text: str | None) -> None:
        self._history.append(JevHistoryEntry(action=action, kind=kind, text=text))


def _takeover(
    reason: str, category: str = SensitiveCategory.IRREVERSIBLE.value
) -> dict[str, dict[str, object]]:
    return {BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER: {"reason": reason, "category": category}}


def _idle_action(output_format: type[BaseModel]) -> dict[str, dict[str, object]]:
    """Return an action that changes nothing and is valid for this step's schema."""
    if "wait" in _registered_actions(output_format):
        return {"wait": {"seconds": 1}}
    return {"done": {"text": _BLOCKED_SUMMARY, "success": False}}


def _is_agent_output(output_format: type[BaseModel]) -> bool:
    return "action" in getattr(output_format, "model_fields", {})


def _offered_operations(registered: set[str]) -> frozenset[JevOperation]:
    """Only operations whose Browser-Use action is registered for this run are offered."""
    return frozenset(
        op for name, ops in _OPERATIONS_BY_ACTION.items() if name in registered for op in ops
    )


def _registered_actions(output_format: type[BaseModel]) -> set[str]:
    """Return the action names in AgentOutput.action's element model.

    Browser-Use builds that model two ways: one model with an optional field per
    action, or (0.11+) a RootModel over a union of single-field models.
    """
    action_model = get_args(output_format.model_fields["action"].annotation)[0]
    fields = getattr(action_model, "model_fields", {})
    if "root" not in fields:
        return set(fields)
    members = get_args(fields["root"].annotation) or (fields["root"].annotation,)
    return {name for member in members for name in getattr(member, "model_fields", {})}


def _output(
    output_format: type[T], action: dict[str, dict[str, object]], goal: str, memory: str
) -> T:
    return output_format.model_validate({"memory": memory, "next_goal": goal, "action": [action]})


def _goal_from_messages(messages: list[BaseMessage]) -> str:
    """Return the task as Browser-Use's own prompt carries it, for an unbound adapter."""
    for message in reversed(messages):
        text = getattr(message, "text", None)
        if not isinstance(text, str):
            continue
        match = _USER_REQUEST.search(text)
        if match:
            return match.group(1)
    return ""


def build_jev_chat_model(*, text_model: BaseChatModel) -> JevChatModel:
    """Return the Jev policy over OpenRouter, with text_model as its text helper.

    Raises BrowserUnavailableError when no OpenRouter key is configured.
    """
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        raise BrowserUnavailableError("Jev is enabled but OPENROUTER_API_KEY is not set.")
    client = JevGatewayClient(
        api_key=api_key,
        model=settings.BROWSER_USE_JEV_MODEL,
        url=settings.BROWSER_USE_JEV_DECISIONS_URL,
    )
    return JevChatModel(client=client, text_model=text_model)


__all__ = ["JevChatModel", "JevGatewayError", "build_jev_chat_model"]
