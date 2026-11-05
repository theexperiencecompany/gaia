import type {
  AuthoredGateView,
  GateEdit,
  SystemGateView,
} from "@shared/api/generated";
import type { GateAuthorLine } from "../constants/gates";
import type { WorkflowFormData } from "../schemas/workflowFormSchema";

/**
 * The gate field of a workflow update: undefined keeps the saved gate, null
 * removes it, a value replaces or switches it. A system gate is only ever
 * switched, and an unchanged condition is not resent, so turning a gate off
 * sends enabled alone.
 */
export function gateEditFor(
  saved: AuthoredGateView | SystemGateView | null | undefined,
  draft: WorkflowFormData["gate"],
): GateEdit | null | undefined {
  const condition = draft.condition.trim();
  if (!saved)
    return condition ? { condition, enabled: draft.enabled } : undefined;
  if (saved.kind === "authored") {
    if (!condition) return null;
    if (condition !== saved.condition) {
      return { condition, enabled: draft.enabled };
    }
  }
  return draft.enabled === saved.enabled
    ? undefined
    : { enabled: draft.enabled };
}

/** Who wrote a saved gate's rule, as its panel says it. */
export function gateAuthorLine(
  saved: AuthoredGateView | SystemGateView,
): GateAuthorLine {
  return saved.kind === "system" ? "system" : saved.author;
}
