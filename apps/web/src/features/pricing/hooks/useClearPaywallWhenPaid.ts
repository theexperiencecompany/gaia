"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

import { pricingApi } from "../api/pricingApi";
import { PAYWALL_STATUS_POLL_MS } from "../constants";
import { useIsPaid } from "./useIsPaid";

/**
 * Takes the paid-only wall down the moment the subscription is real — the
 * wall refuses ordinary closes, so this is the only caller of `closeModal`.
 * Needed both for a cold-cache render that raised the wall on an unknown
 * status, and when checkout finishes elsewhere (e.g. the desktop popup). It
 * also polls, since `["subscription-status"]` is stale with no refetch-on-focus,
 * or the popup's wall would survive a paid subscription until app restart.
 */
export function useClearPaywallWhenPaid(): void {
  const open = useUpgradeModalStore((state) => state.open);
  const closeModal = useUpgradeModalStore((state) => state.closeModal);
  const { isPaid, isUnknown } = useIsPaid();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (open && !isUnknown && isPaid) closeModal({ force: true });
  }, [open, isUnknown, isPaid, closeModal]);

  useEffect(() => {
    if (!open || isPaid) return;
    // A poll from an idle tab, so it must not count the user as active.
    const poll = () =>
      void queryClient.prefetchQuery({
        queryKey: ["subscription-status"],
        queryFn: () => pricingApi.getSubscriptionStatus({ background: true }),
        staleTime: 0,
      });
    const interval = setInterval(poll, PAYWALL_STATUS_POLL_MS);
    return () => clearInterval(interval);
  }, [open, isPaid, queryClient]);
}
