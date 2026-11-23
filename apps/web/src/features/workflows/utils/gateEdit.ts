import type {
  AuthoredGateView,
  GateEdit,
  SystemGateView,
} from "@shared/api/generated";
import { GATE_SENTENCE_PREFIX } from "../constants/gates";
import type { WorkflowFormData } from "../schemas/workflowFormSchema";

/**
 * The gate field of a workflow update: undefined keeps the saved gate, a value
 * rewrites or switches it. Users never add or remove a rule, GAIA writes it; a
 * system gate is only switched, so turning a gate off sends enabled alone.
 */
export function gateEditFor(
  saved: AuthoredGateView | SystemGateView | null | undefined,
  draft: WorkflowFormData["gate"],
): GateEdit | undefined {
  if (!saved) return undefined;
  const condition = draft.condition.trim();
  if (saved.kind === "authored" && condition !== saved.condition) {
    return { condition, enabled: draft.enabled };
  }
  return draft.enabled === saved.enabled
    ? undefined
    : { enabled: draft.enabled };
}

/** A stored condition as the sentence its row reads, e.g. "Only when a customer writes about billing". */
export function gateSentence(condition: string): string {
  const clause = condition.trim();
  if (/^(only )?when\b/i.test(clause)) {
    return clause.charAt(0).toUpperCase() + clause.slice(1);
  }
  const lowered = /^[A-Z][a-z]/.test(clause)
    ? clause.charAt(0).toLowerCase() + clause.slice(1)
    : clause;
  return `${GATE_SENTENCE_PREFIX} ${lowered}`;
}
