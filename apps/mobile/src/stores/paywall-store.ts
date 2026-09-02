import type { SubscriptionRequiredDetail } from "@gaia/shared";
import { create } from "zustand";

interface PaywallState {
  /** The 402's offer while the user is blocked, else null. */
  offer: SubscriptionRequiredDetail | null;
  setBlocked: (offer: SubscriptionRequiredDetail) => void;
  clearBlock: () => void;
}

/**
 * GAIA is paid-only. When the backend refuses a turn with 402, the offer it
 * returned (message, checkout link, discount code) lands here so the chat
 * screen can show the wall instead of a generic failure.
 *
 * Separate from the chat store on purpose: the block belongs to the account,
 * not to one conversation — every conversation is refused the same way.
 */
export const usePaywallStore = create<PaywallState>((set) => ({
  offer: null,
  setBlocked: (offer) => set({ offer }),
  clearBlock: () => set({ offer: null }),
}));
