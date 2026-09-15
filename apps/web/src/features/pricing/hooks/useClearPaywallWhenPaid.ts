"use client";

import { useEffect } from "react";

import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

import { PAYWALL_STATUS_POLL_MS } from "../constants";
import { useIsPaid } from "./useIsPaid";
import { useUserSubscriptionStatus } from "./usePricing";

/**
 * Takes the paid-only wall down the moment the subscription behind it is
 * real, wherever the wall is being rendered.
 *
 * The wall refuses ordinary closes — that is what makes it a wall — so
 * something has to close it for the user, and nothing else in the app ever
 * calls `closeModal`. Two situations need it:
 *
 * - a cold-cache render raised the wall while the plan status was still
 *   unknown (see `useComposerSubmit`, which lets the action through while
 *   unknown rather than trapping a Pro user), and
 * - the checkout that lifts the wall finished somewhere else entirely: the
 *   desktop popup sends the user to subscribe in their browser, and the
 *   window holding the wall never hears about it.
 *
 * That second case is also why this asks again on a timer. The
 * `["subscription-status"]` query is a minute stale and never refetches on
 * focus, so a window sitting behind a wall would otherwise never re-read the
 * plan — the popup's wall survived a successful subscription until the app
 * was restarted. The asking stops the moment the answer is yes, and never
 * starts while no wall is up.
 */
export function useClearPaywallWhenPaid(): void {
  const open = useUpgradeModalStore((state) => state.open);
  const closeModal = useUpgradeModalStore((state) => state.closeModal);
  const { isPaid, isUnknown } = useIsPaid();
  const { refetch } = useUserSubscriptionStatus();

  useEffect(() => {
    if (open && !isUnknown && isPaid) closeModal({ force: true });
  }, [open, isUnknown, isPaid, closeModal]);

  useEffect(() => {
    if (!open || isPaid) return;
    const interval = setInterval(() => void refetch(), PAYWALL_STATUS_POLL_MS);
    return () => clearInterval(interval);
  }, [open, isPaid, refetch]);
}
