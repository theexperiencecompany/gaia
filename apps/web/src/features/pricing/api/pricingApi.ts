import type { AxiosError } from "axios";

import { apiService } from "@/lib/api";

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

export interface CreateSubscriptionRequest {
  product_id: string;
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
  webhook_verified: boolean;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
}

export interface UserSubscriptionStatus {
  user_id: string;
  current_plan?: Plan;
  subscription?: Subscription;
  is_subscribed: boolean;
  days_remaining?: number;
  can_upgrade: boolean;
  can_downgrade: boolean;
}

// Helper function for consistent error handling
interface ApiErrorResponse {
  detail?: string;
  message?: string;
}

const handleApiError = (error: unknown, context: string): never => {
  let errorMessage = "An unexpected error occurred";
  let status: number | undefined;

  if (error && typeof error === "object" && "isAxiosError" in error) {
    const axiosError = error as AxiosError<ApiErrorResponse>;
    errorMessage =
      axiosError.response?.data?.detail ||
      axiosError.response?.data?.message ||
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

  // Verify payment completion after redirect
  async verifyPayment(): Promise<PaymentVerificationResponse> {
    try {
      return await apiService.post<PaymentVerificationResponse>(
        "/payments/verify-payment",
        {},
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
}

export const pricingApi = new PricingApi();
