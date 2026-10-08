"use client";

import type { EventProperties } from "@gaia/shared/analytics/events";
import { useRouter } from "next/navigation";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { track } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import type { CheckoutSource } from "../api/pricingApi";
import { writePendingCheckout } from "../lib/pendingCheckout";
import {
  type CheckoutPhase,
  isCheckoutSettled,
} from "../stores/checkoutOverlayStore";
import type { PlanViewerState } from "../types";
import { useDodoPayments } from "./useDodoPayments";

/** The tier a pricing card sells; the card's display title is copy, this is the analytics value. */
export type PlanTier = EventProperties["pricing:plan_selected"]["plan_tier"];

interface PricingCardCtaInput {
  planTier: PlanTier;
  /** Where this checkout is started from; rides to the server for funnel
   * attribution and decides where Dodo sends the browser afterwards. */
  checkoutSource?: CheckoutSource;
  price: number;
  durationIsMonth: boolean;
  planId: string | undefined;
  planViewerState: PlanViewerState;
}

interface PricingCardCta {
  buttonText: string;
  /** Held disabled while a checkout is in flight or the plan is unresolved. */
  isCtaDisabled: boolean;
  isConfirmingPayment: boolean;
  isCheckoutLate: boolean;
  paymentError: string | null;
  onGetStarted: () => Promise<void>;
}

/** Everything the pricing card's call to action needs to decide and do. */
export function usePricingCardCta({
  planTier,
  price,
  durationIsMonth,
  planId,
  planViewerState,
  checkoutSource = "pricing_card",
}: PricingCardCtaInput): PricingCardCta {
  const isCurrentPlan = planViewerState === "current";
  const isSubscribedElsewhere = planViewerState === "subscribedElsewhere";
  const isSubscriptionStatusUnknown = planViewerState === "unknown";
  const hasActiveSubscription = isCurrentPlan || isSubscribedElsewhere;

  const {
    openCheckoutOverlay,
    checkoutPhase,
    error: paymentError,
  } = useDodoPayments();
  const user = useCurrentUser();
  const router = useRouter();

  const onGetStarted = async () => {
    track("pricing:plan_selected", {
      plan_id: planId,
      plan_tier: planTier,
      price,
      is_monthly: durationIsMonth,
      is_current_plan: isCurrentPlan,
      has_active_subscription: hasActiveSubscription,
      is_free_plan: price === 0,
    });

    if (price === 0) {
      if (user.userId) router.push("/c");
      else router.push("/signup");
      return;
    }

    if (!user.userId) {
      // Carry the chosen plan across OAuth signup; useCheckoutResume picks it
      // up once authenticated and goes straight to the Dodo checkout.
      if (planId) writePendingCheckout(planId);
      router.push("/login");
      return;
    }

    // Plan status not yet resolved — isCurrentPlan/hasActiveSubscription read
    // as false here, which could otherwise send an already-subscribed user into
    // a duplicate checkout. The button is disabled meanwhile, so this is a defensive no-op.
    if (isSubscriptionStatusUnknown) return;

    if (isCurrentPlan && hasActiveSubscription) {
      toast.info("This is your current active plan");
      return;
    }

    if (hasActiveSubscription && !isCurrentPlan) {
      toast.info(
        "Please cancel your current subscription before subscribing to a different plan",
      );
      return;
    }

    if (!planId) {
      toast.error("Plan not available. Please try again later.");
      return;
    }

    await openCheckoutOverlay(durationIsMonth ? "monthly" : "yearly", {
      source: checkoutSource,
    });
  };

  return {
    buttonText: getButtonText({
      checkoutPhase,
      isSubscriptionStatusUnknown,
      isCurrentPlan,
      hasActiveSubscription,
    }),
    isCtaDisabled:
      !isCheckoutSettled(checkoutPhase) ||
      isSubscriptionStatusUnknown ||
      (isCurrentPlan && hasActiveSubscription),
    isConfirmingPayment:
      checkoutPhase === "confirming" || checkoutPhase === "timeout",
    isCheckoutLate: checkoutPhase === "timeout",
    paymentError,
    onGetStarted,
  };
}

interface ButtonTextInput {
  checkoutPhase: CheckoutPhase;
  isSubscriptionStatusUnknown: boolean;
  isCurrentPlan: boolean;
  hasActiveSubscription: boolean;
}

function getButtonText({
  checkoutPhase,
  isSubscriptionStatusUnknown,
  isCurrentPlan,
  hasActiveSubscription,
}: ButtonTextInput): string {
  if (checkoutPhase === "creating") return "Creating subscription...";
  if (checkoutPhase === "open") return "Checkout open";
  if (isSubscriptionStatusUnknown) return "Checking your plan...";
  if (isCurrentPlan && hasActiveSubscription) return "Current Plan";
  if (hasActiveSubscription && !isCurrentPlan) return "Switch Plan";
  return "Subscribe";
}
