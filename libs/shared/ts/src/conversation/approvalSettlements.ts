import { create } from "zustand";
import {
  type ApprovalSettlement,
  settleApprovalToolData,
} from "../utils/approvalSettle";

/** One verdict by approval id, whichever conversation shows its card. */
export type ApprovalVerdicts = Readonly<
  Record<string, Omit<ApprovalSettlement, "conversation_id">>
>;

interface ApprovalSettlementState {
  settled: ApprovalVerdicts;
  settle: (settlement: Omit<ApprovalSettlement, "conversation_id">) => void;
}

/**
 * Approval verdicts that reach this device before or instead of the log: its own
 * decision's response, and the `hil_approval_decided` push (which alone carries an
 * agent's withdrawal and an action result the log has no work for). Rows lay these
 * over the cards the log shows.
 */
export const useApprovalSettlementStore = create<ApprovalSettlementState>()(
  (set) => ({
    settled: {},
    settle: (settlement) =>
      set((state) => ({
        settled: { ...state.settled, [settlement.approval_id]: settlement },
      })),
  }),
);

/** The cards with each verdict in verdicts laid over the approval card it names. */
export function withVerdicts<T extends { tool_name: string; data: unknown }>(
  cards: readonly T[],
  verdicts: ApprovalVerdicts,
): T[] {
  let shown = [...cards];
  for (const card of cards) {
    const approvalId = (card.data as { approval_id?: unknown } | null)
      ?.approval_id;
    const verdict =
      typeof approvalId === "string" ? verdicts[approvalId] : undefined;
    if (verdict)
      shown = settleApprovalToolData(shown, verdict).entries ?? shown;
  }
  return shown;
}
