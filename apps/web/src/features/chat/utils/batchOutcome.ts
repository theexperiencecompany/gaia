import type { ApprovalStatus } from "@shared/chat";

/** Why a batch item did not commit — the server's vocabulary (ledger_decide.py). */
export const BATCH_OUTCOME_REASON = {
  NOT_FOUND: "not_found",
  STALE: "stale",
  ERROR: "error",
} as const;

/** Server-reported ledger states that name a real card status. */
const KNOWN_STATUSES: ReadonlySet<string> = new Set<string>([
  "pending",
  "approved",
  "denied",
  "timeout",
  "abandoned",
  "auto_approved",
  "revoked",
  "executed",
  "failed",
  "unknown",
]);

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
  tapped: ApprovalStatus,
): ApprovalStatus {
  if (
    outcomeStatus !== null &&
    outcomeStatus !== undefined &&
    KNOWN_STATUSES.has(outcomeStatus)
  ) {
    return outcomeStatus as ApprovalStatus;
  }
  return tapped;
}
