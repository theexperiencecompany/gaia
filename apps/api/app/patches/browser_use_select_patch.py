"""Pick a dropdown option without option.selected, which Obscura ignores.

Measured 2026-09-19, raw port and through our host alike: assigning
select.value picks the option and FormData then sends it; assigning
option.selected only raises a second option's flag; assigning selectedIndex
moves the selection while its getter still reads the old index.

Browser-Use's handler writes all three in that order, then verifies with
element.value !== expectedValue. The middle write leaves the element
inconsistent, the check fails, and Jev is told the page reverted a selection a
plain value assignment would have made -- so it retries forever. So this
assigns value alone (or selectedIndex when option values repeat, the one case
value cannot address) and verifies against selectedIndex.

Pinned to browser-use==0.11.13; the import fails loudly if the handler moves.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.events import SelectDropdownOptionEvent
    from browser_use.dom.views import EnhancedDOMTreeNode

_original_on_select = DefaultActionWatchdog.on_SelectDropdownOptionEvent

# Matches the option by its visible text or its value, case-insensitively, the
# way Browser-Use's own script does -- the model only ever sees the text.
_SELECT_JS = """function(targetText) {
  const el = this;
  if (!el.options) return JSON.stringify({error: 'not-a-select', tag: el.tagName});
  const options = Array.from(el.options);
  const wanted = String(targetText).trim().toLowerCase();
  const index = options.findIndex(
    (o) => o.text.trim().toLowerCase() === wanted || o.value.trim().toLowerCase() === wanted
  );
  if (index < 0) {
    return JSON.stringify({
      error: 'not-found',
      options: options.map((o) => ({text: o.text.trim(), value: o.value})),
    });
  }
  const option = options[index];
  el.focus();
  // `value =` is the one assignment Obscura honours end to end; it can only
  // address an option by value, so a duplicated value falls back to the index.
  const unique = options.filter((o) => o.value === option.value).length === 1;
  if (unique) { el.value = option.value; } else { el.selectedIndex = index; }
  el.dispatchEvent(new Event('input', {bubbles: true, cancelable: true}));
  el.dispatchEvent(new Event('change', {bubbles: true, cancelable: true}));
  el.blur();
  // selectedIndex is the honest read-back here; `value` lags on Obscura after
  // an index write, and a page framework that truly reverted the pick moves both.
  const chosen = el.options[el.selectedIndex];
  return JSON.stringify({
    selected: !!chosen && chosen.text.trim() === option.text.trim(),
    text: option.text.trim(),
    value: option.value,
    index: el.selectedIndex,
    landed_on: chosen ? chosen.text.trim() : null,
  });
}"""


def _failure(short: str, long: str) -> dict[str, str]:
    """Build the failure shape tools/service.py's select_dropdown reads."""
    return {"success": "false", "short_term_memory": short, "long_term_memory": long}


def _is_native_select(node: EnhancedDOMTreeNode) -> bool:
    """Say whether this is a real <select>; anything else is Browser-Use's ARIA path."""
    # tag_name is Browser-Use's lowercased node_name, never missing.
    return node.tag_name == "select"


async def on_SelectDropdownOptionEvent(
    self: DefaultActionWatchdog, event: SelectDropdownOptionEvent
) -> dict[str, str]:
    """Select the option whose text or value matches, and report what the page ended up on."""
    node = event.node
    # Browser-Use's own handler also drives role=menu/listbox/combobox widgets,
    # which have no options to assign; only the <select> path is broken here.
    if not _is_native_select(node):
        return await _original_on_select(self, event)

    cdp_session = await self.browser_session.cdp_client_for_node(node)
    resolved: dict[str, Any] = dict(
        await cdp_session.cdp_client.send.DOM.resolveNode(
            params={"backendNodeId": node.backend_node_id}, session_id=cdp_session.session_id
        )
    )
    object_id = (resolved.get("object") or {}).get("objectId")
    if not object_id:
        return _failure(
            f"Could not reach the dropdown to select '{event.text}'.",
            f"Dropdown at index {node.backend_node_id} could not be resolved",
        )

    response: dict[str, Any] = dict(
        await cdp_session.cdp_client.send.Runtime.callFunctionOn(
            params={
                "functionDeclaration": _SELECT_JS,
                "objectId": object_id,
                "returnByValue": True,
                "arguments": [{"value": event.text}],
            },
            session_id=cdp_session.session_id,
        )
    )
    raw = (response.get("result") or {}).get("value")
    if response.get("exceptionDetails") or not isinstance(raw, str):
        log.warning(
            f"{LogTag.BROWSER} Dropdown selection script did not run",
            error_type="SelectScriptFailed",
        )
        return _failure(
            f"Could not select '{event.text}' in the dropdown.",
            f"Dropdown selection of '{event.text}' failed to run",
        )

    outcome: dict[str, Any] = json.loads(raw)
    if outcome.get("error") == "not-found":
        available = ", ".join(str(o["text"]) for o in outcome["options"])
        return _failure(
            f"No option '{event.text}' in this dropdown. Available: {available}",
            f"Dropdown has no option '{event.text}'",
        )
    if outcome.get("error"):
        return _failure(
            f"Element is a <{outcome.get('tag')}>, not a dropdown.",
            f"Index {node.backend_node_id} is not a <select>",
        )
    if not outcome.get("selected"):
        return _failure(
            f"Selecting '{event.text}' left the dropdown on '{outcome.get('landed_on')}'.",
            f"Dropdown reverted the selection of '{event.text}'",
        )
    return {
        "success": "true",
        "message": f"Selected option: {outcome['text']} (value: {outcome['value']})",
    }


def apply() -> None:
    """Route every dropdown selection through the assignment Obscura honours."""
    # type.__setattr__ mirrors the stealth patch: an honest rebind of a coroutine
    # method that keeps mypy satisfied without an ignore.
    type.__setattr__(
        DefaultActionWatchdog, "on_SelectDropdownOptionEvent", on_SelectDropdownOptionEvent
    )


apply()
