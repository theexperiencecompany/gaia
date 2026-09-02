"use client";

import { useRouter } from "next/navigation";
import { useUser } from "@/features/auth/hooks/useUser";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import type { CheckoutSource } from "../api/pricingApi";
import { writePendingCheckout } from "../lib/pendingCheckout";
import type { CheckoutPhase } from "../stores/checkoutOverlayStore";
import type { PlanViewerState } from "../types";
import { PLAN_DISPLAY_NAME } from "../utils/planPredicates";
import { useDodoPayments } from "./useDodoPayments";

interface PricingCardCtaInput {
  /** Where this checkout is started from; rides to the server for funnel
   * attribution and decides where Dodo sends the browser afterwards. */
  checkoutSource?: CheckoutSource;
  title: string;
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
  /** GAIA is paid-only; kept as a defensive branch — see PricingCardCta. */
  isFree: boolean;
  isOnFreePlan: boolean;
  onGetStarted: () => Promise<void>;
}

/** Everything the pricing card's call to action needs to decide and do. */
export function usePricingCardCta({
  title,
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
  const user = useUser();
  const router = useRouter();

  const onGetStarted = async () => {
    trackEvent(ANALYTICS_EVENTS.PRICING_PLAN_SELECTED, {
      plan_title: title,
      plan_id: planId,
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

    // Plan status not yet resolved — isCurrentPlan/hasActiveSubscription
    // read as false in this window, which would otherwise let an already-
    // subscribed user click straight into a duplicate checkout. The button
    // is disabled while this is true, so this is a defensive no-op.
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
      title,
    }),
    isCtaDisabled:
      checkoutPhase !== "idle" ||
      isSubscriptionStatusUnknown ||
      (isCurrentPlan && hasActiveSubscription),
    isConfirmingPayment:
      checkoutPhase === "confirming" || checkoutPhase === "timeout",
    isCheckoutLate: checkoutPhase === "timeout",
    paymentError,
    isFree: price === 0,
    isOnFreePlan: !!user && !hasActiveSubscription,
    onGetStarted,
  };
}

interface ButtonTextInput {
  checkoutPhase: CheckoutPhase;
  isSubscriptionStatusUnknown: boolean;
  isCurrentPlan: boolean;
  hasActiveSubscription: boolean;
  title: string;
}

function getButtonText({
  checkoutPhase,
  isSubscriptionStatusUnknown,
  isCurrentPlan,
  hasActiveSubscription,
  title,
}: ButtonTextInput): string {
  if (checkoutPhase === "creating") return "Creating subscription...";
  if (checkoutPhase === "open") return "Checkout open";
  if (isSubscriptionStatusUnknown) return "Checking your plan...";
  if (isCurrentPlan && hasActiveSubscription) return "Current Plan";
  if (hasActiveSubscription && !isCurrentPlan) return "Switch Plan";
  // The card already says "GAIA"; "Get GAIA GAIA" is not a sentence.
  return title === PLAN_DISPLAY_NAME ? `Get ${title}` : `Get GAIA ${title}`;
}
