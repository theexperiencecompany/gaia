"use client";

import { useEffect } from "react";
import { useLogout } from "@/features/auth/hooks/useLogout";
import { usePathname } from "@/i18n/navigation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

import { paywallCopyFor } from "../constants";
import { isProPlan } from "../utils/planPredicates";
import { useClearPaywallWhenPaid } from "./useClearPaywallWhenPaid";
import { useDodoPayments } from "./useDodoPayments";
import { useIsPaid } from "./useIsPaid";
import { usePricing } from "./usePricing";

export function useUpgradeModal() {
  const { open, offer, dismissible, closeModal } = useUpgradeModalStore();
  const pathname = usePathname();
  const { plans } = usePricing();
  const { logout } = useLogout();
  const { openCheckoutOverlay, checkoutPhase } = useDodoPayments();
  const { hasEverSubscribed } = useIsPaid();
  const copy = paywallCopyFor(hasEverSubscribed);
  const isConfirming =
    checkoutPhase === "confirming" || checkoutPhase === "timeout";
  // The wizard owns payment on its own stage; a 402 from a background request
  // there must not stack this modal on top of it.
  const isOnboardingRoute = pathname === "/onboarding";

  useClearPaywallWhenPaid();

  // The impression: one per wall that actually reached the screen. The server
  // already captures the 402 behind it; whether it was rendered is the one
  // thing only the browser knows — so it must not fire for the route that
  // renders nothing, and must not re-fire when another 402 arrives (the store
  // leaves an open wall alone, and the offer is read here rather than
  // tracked, so neither can inflate it).
  useEffect(() => {
    if (!open || isOnboardingRoute) return;
    const {
      dismissible: shownAsDismissible,
      offer: shownOffer,
      source,
    } = useUpgradeModalStore.getState();
    trackEvent(ANALYTICS_EVENTS.PAYWALL_MODAL_VIEWED, {
      dismissible: shownAsDismissible,
      has_discount_code: Boolean(shownOffer?.discountCode),
      source,
    });
  }, [open, isOnboardingRoute]);

  // Monthly Pro is the default enforcement offer — same tier PricingCards
  // leads with, just without the billing-period tabs (that mode has one job).
  const proPlan = plans.find(
    (plan) => isProPlan(plan) && plan.duration === "monthly",
  );

  const handleSubscribe = () => {
    void openCheckoutOverlay("monthly", { source: "paywall_modal" });
  };

  return {
    open,
    offerMessage: offer?.message,
    discountCode: offer?.discountCode,
    discountPercent: offer?.discountPercent,
    dismissible,
    closeModal,
    plans,
    proPlan,
    copy,
    isConfirming,
    checkoutPhase,
    handleSubscribe,
    logout,
    isOnboardingRoute,
  };
}
