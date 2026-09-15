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

import type { AxiosError } from "axios";
import { getErrorMessage } from "@/lib/api/errors";
import { api } from "@/lib/api/typed";

export type Plan = PlanResponse;

/** Where in the product a checkout was started. Mirrors `CheckoutSource` in
 *  `app/models/payment_models.py`; the server emits it as a property on
 *  `payment:checkout_started`, so a new surface adds a member on both sides. */

export type Subscription = SubscriptionDocument;

// Helper function for consistent error handling
const handleApiError = (error: unknown, context: string): never => {
  let errorMessage = "An unexpected error occurred";
  let status: number | undefined;

  if (error && typeof error === "object" && "isAxiosError" in error) {
    const axiosError = error as AxiosError;
    errorMessage =
      getErrorMessage(axiosError.response?.data) ||
      axiosError.message ||
      errorMessage;
    status = axiosError.response?.status;
  } else if (error instanceof Error) {
    errorMessage = error.message;
  }

  console.error(`${context} failed:`, {
    error: errorMessage,
    status,
  });

  throw new Error(errorMessage);
};

class PricingApi {
  // Get all available plans
  async getPlans(activeOnly = true): Promise<Plan[]> {
    try {
      return await api.get("/api/v1/payments/plans", {
        query: { active_only: activeOnly },
      });
    } catch (error) {
      return handleApiError(error, "Get plans");
    }
  }

  // Create subscription and get payment link
  async createSubscription(
    data: CreateSubscriptionRequest,
  ): Promise<CreateSubscriptionResponse> {
    try {
      return await api.post("/api/v1/payments/subscriptions", { body: data });
    } catch (error) {
      return handleApiError(error, "Create subscription");
    }
  }

  // Mint the Dodo checkout session the embedded overlay opens. The server
  // resolves the Pro plan for the cycle, so no product id crosses the wire.
  async createCheckoutSession(
    data: CreateCheckoutSessionRequest,
  ): Promise<CreateSubscriptionResponse> {
    try {
      return await api.post("/api/v1/payments/checkout-session", {
        body: data,
      });
    } catch (error) {
      return handleApiError(error, "Create checkout session");
    }
  }

  // Verify payment completion after redirect. `subscriptionId` (from the Dodo
  // return URL) lets the server reconcile against Dodo when the webhook that
  // would have created the row never arrived.
  async verifyPayment(
    subscriptionId?: string | null,
  ): Promise<PaymentVerificationResponse> {
    try {
      return await api.post("/api/v1/payments/verify-payment", {
        body: subscriptionId ? { subscription_id: subscriptionId } : {},
      });
    } catch (error) {
      return handleApiError(error, "Verify payment");
    }
  }

  // Get user subscription status
  async getSubscriptionStatus(): Promise<UserSubscriptionStatus> {
    try {
      return await api.get("/api/v1/payments/subscription-status");
    } catch (error) {
      return handleApiError(error, "Get subscription status");
    }
  }

  // Cancel the user's subscription (effective at the end of the billing period)
  async cancelSubscription(): Promise<UserSubscriptionStatus> {
    try {
      return await api.post("/api/v1/payments/subscriptions/cancel", {
        successMessage: "Subscription cancelled",
        errorMessage: "Failed to cancel subscription",
      });
    } catch (error) {
      return handleApiError(error, "Cancel subscription");
    }
  }
}

export const pricingApi = new PricingApi();
