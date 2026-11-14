/** Why a batch item did not commit — the server's vocabulary (ledger_decide.py). */
export const BATCH_OUTCOME_REASON = {
  NOT_FOUND: "not_found",
  ERROR: "error",
} as const;
