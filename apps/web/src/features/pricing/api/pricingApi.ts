import type { AxiosError } from "axios";

import { apiService } from "@/lib/api/service";
import { getErrorMessage } from "@/utils/interceptorUtils";

export interface Plan {
  id: string;
  dodo_product_id: string; // Add Dodo product ID field
  name: string;
  description?: string;
  amount: number;
  currency: string;
  duration: "monthly" | "yearly";
  max_users?: number;
  features: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** Where in the product a checkout was started. Mirrors `CheckoutSource` in
 *  `app/models/payment_models.py`; the server emits it as a property on
 *  `payment:checkout_started`, so a new surface adds a member on both sides. */
export type CheckoutSource =
  | "paywall_modal"
  | "pricing_card"
  | "payment_retry"
  | "checkout_resume"
  | "onboarding";

export interface CreateSubscriptionRequest {
  product_id: string;
  discount_code?: string;
  source?: CheckoutSource;
}

export interface CreateCheckoutSessionRequest {
  billing_cycle: "monthly" | "yearly";
  source: CheckoutSource;
}

export interface CreateSubscriptionResponse {
  subscription_id: string;
  payment_link: string;
  status: string;
}

export interface PaymentVerificationResponse {
  payment_completed: boolean;
  subscription_id?: string;
  message: string;
}

export interface Subscription {
  id: string;
  dodo_subscription_id: string;
  user_id: string;
  product_id: string;
  status: string;
  quantity: number;
  payment_link?: string;
  webhook_verified?: boolean;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
  // Billing info from webhook
  currency?: string;
  recurring_pre_tax_amount?: number;
  next_billing_date?: string;
  previous_billing_date?: string;
  payment_frequency_interval?: string;
  subscription_period_count?: number;
  subscription_period_interval?: string;
  cancelled_at?: string;
  cancel_at_next_billing_date?: boolean;
}

export interface UserSubscriptionStatus {
  user_id: string;
  current_plan?: Plan;
  subscription?: Subscription;
  is_subscribed: boolean;
  days_remaining?: number;
  can_upgrade: boolean;
  can_downgrade: boolean;
  // Legacy fields from backend
  has_subscription?: boolean;
  plan_type?: "free" | "pro";
  status?: string;
  /** Whether this user has ever had a subscription, in any status — separates a
   *  lapsed subscriber from one who has never paid, which the paywall copy
   *  keys on. */
  has_ever_subscribed?: boolean;
}

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
      return await apiService.get<Plan[]>(
        `/payments/plans?active_only=${activeOnly}`,
      );
    } catch (error) {
      return handleApiError(error, "Get plans");
    }
  }

  // Create subscription and get payment link
  async createSubscription(
    data: CreateSubscriptionRequest,
  ): Promise<CreateSubscriptionResponse> {
    try {
      return await apiService.post<CreateSubscriptionResponse>(
        "/payments/subscriptions",
        data,
      );
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
      return await apiService.post<CreateSubscriptionResponse>(
        "/payments/checkout-session",
        data,
      );
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
      return await apiService.post<PaymentVerificationResponse>(
        "/payments/verify-payment",
        subscriptionId ? { subscription_id: subscriptionId } : {},
      );
    } catch (error) {
      return handleApiError(error, "Verify payment");
    }
  }

  // Get user subscription status
  async getSubscriptionStatus(): Promise<UserSubscriptionStatus> {
    try {
      return await apiService.get<UserSubscriptionStatus>(
        "/payments/subscription-status",
      );
    } catch (error) {
      return handleApiError(error, "Get subscription status");
    }
  }

  // Cancel the user's subscription (effective at the end of the billing period)
  async cancelSubscription(): Promise<UserSubscriptionStatus> {
    try {
      return await apiService.post<UserSubscriptionStatus>(
        "/payments/subscriptions/cancel",
        {},
        {
          successMessage: "Subscription cancelled",
          errorMessage: "Failed to cancel subscription",
        },
      );
    } catch (error) {
      return handleApiError(error, "Cancel subscription");
    }
  }
}

export const pricingApi = new PricingApi();
