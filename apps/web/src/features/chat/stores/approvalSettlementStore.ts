import type { ApprovalSettlement } from "@shared/utils";
import { create } from "zustand";

type Settlement = Omit<ApprovalSettlement, "conversation_id">;

interface ApprovalSettlementState {
  /** By approval id: the verdicts this device learned before the log carries them. */
  settled: Readonly<Record<string, Settlement>>;
  settle: (settlement: Settlement) => void;
}

/**
 * Approval verdicts that reach this device outside the conversation's log: its own
 * decision's response, and the `hil_approval_decided` push (which also carries
 * revoked, executed and failed). The rows lay these over the cards the log shows.
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
