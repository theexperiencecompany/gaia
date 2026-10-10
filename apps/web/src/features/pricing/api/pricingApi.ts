import type {
  CreateCheckoutSessionRequest,
  CreateSubscriptionRequest,
  CreateSubscriptionResponse,
  PaymentVerificationResponse,
  PlanResponse,
  SubscriptionDocument,
  UserSubscriptionStatus,
} from "@shared/api/generated";

export type {
  CheckoutSource,
  PaymentVerificationResponse,
  UserSubscriptionStatus,
} from "@shared/api/generated";

import { api } from "@/lib/api/typed";

export type Plan = PlanResponse;

/** Where in the product a checkout was started. Mirrors `CheckoutSource` in
 *  `app/models/payment_models.py`; the server emits it as a property on
 *  `payment:checkout_started`, so a new surface adds a member on both sides. */

export type Subscription = SubscriptionDocument;

/**
 * Every call throws the shared `ApiError`, already logged and toasted by the
 * typed client, whose `message` is the backend's own words and whose
 * `envelope.code` is what a caller branches on. Nothing here re-wraps it.
 */
class PricingApi {
  // Get all available plans
  getPlans(activeOnly = true): Promise<Plan[]> {
    return api.get("/api/v1/payments/plans", {
      query: { active_only: activeOnly },
    });
  }

  // Create subscription and get payment link
  createSubscription(
    data: CreateSubscriptionRequest,
  ): Promise<CreateSubscriptionResponse> {
    return api.post("/api/v1/payments/subscriptions", { body: data });
  }

  // Mint the Dodo checkout session the embedded overlay opens. The server
  // resolves the Pro plan for the cycle, so no product id crosses the wire.
  createCheckoutSession(
    data: CreateCheckoutSessionRequest,
  ): Promise<CreateSubscriptionResponse> {
    return api.post("/api/v1/payments/checkout-session", { body: data });
  }

  // Verify payment completion after redirect. `subscriptionId` (from the Dodo
  // return URL) lets the server reconcile against Dodo when the webhook that
  // would have created the row never arrived.
  verifyPayment(
    subscriptionId?: string | null,
  ): Promise<PaymentVerificationResponse> {
    return api.post("/api/v1/payments/verify-payment", {
      body: subscriptionId ? { subscription_id: subscriptionId } : {},
    });
  }

  // Get user subscription status
  getSubscriptionStatus(): Promise<UserSubscriptionStatus> {
    return api.get("/api/v1/payments/subscription-status");
  }

  // Cancel the user's subscription (effective at the end of the billing period)
  cancelSubscription(): Promise<UserSubscriptionStatus> {
    return api.post("/api/v1/payments/subscriptions/cancel", {
      successMessage: "Subscription cancelled",
      errorMessage: "Failed to cancel subscription",
    });
  }
}

export const pricingApi = new PricingApi();
