import type { SettledApprovalCardData } from "@shared/chat";
import { isKnownApprovalStatus } from "@shared/utils";

type SettledStatus = SettledApprovalCardData["status"];

/** Why a batch item did not commit — the server's vocabulary (ledger_decide.py). */
export const BATCH_OUTCOME_REASON = {
  NOT_FOUND: "not_found",
  STALE: "stale",
  ERROR: "error",
} as const;

/**
 * Settle a batch item to the server's reported state, not the tapped button.
 *
 * A `not_found` batch outcome means the row was already decided elsewhere
 * (lost CAS race, other tab, revoke) — painting the just-tapped verdict
 * overwrites the real one (e.g. approve tap over an already-denied row).
 * Prefer the server's `status` when it names a known card state; fall back
 * to the tapped verdict only when the server sent nothing (old path).
 */
export function resolveBatchOutcomeStatus(
  outcomeStatus: string | null | undefined,
  tapped: SettledStatus,
): SettledStatus {
  if (
    outcomeStatus != null &&
    isKnownApprovalStatus(outcomeStatus) &&
    outcomeStatus !== "pending"
  ) {
    return outcomeStatus;
  }
  return tapped;
}
