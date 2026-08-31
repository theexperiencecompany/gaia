import type { AxiosError } from "axios";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";

import {
  showFeatureRestrictedToast,
  showRateLimitToast,
  showTokenLimitToast,
} from "@/components/shared/RateLimitToast";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";
import { toast } from "@/lib/toast";
import { useLoginModalStore } from "@/stores/loginModalStore";
import {
  type PaywallOffer,
  usePaywallModalStore,
} from "@/stores/paywallModalStore";

interface ErrorHandlerDependencies {
  router: AppRouterInstance;
}

const getErrorCode = (data: unknown): string | undefined => {
  const detail =
    data && typeof data === "object" && "detail" in data
      ? (data as { detail: unknown }).detail
      : undefined;
  if (detail && typeof detail === "object" && "error_code" in detail)
    return (detail as { error_code?: string }).error_code;
  return undefined;
};

/**
 * Extracts a human-readable message from an Axios error response body,
 * handling both string `detail` and the structured `{ message, ... }` detail
 * the backend returns for auth / integration / rate-limit errors. Prevents an
 * object `detail` from rendering as the literal "[object Object]".
 */
export const getErrorMessage = (data: unknown): string | undefined => {
  const detail =
    data && typeof data === "object" && "detail" in data
      ? (data as { detail: unknown }).detail
      : undefined;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  if (data && typeof data === "object" && "message" in data) {
    const message = (data as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return undefined;
};

/**
 * Surfaces API error UI for app-shell requests. Only mounted inside the (main)
 * provider tree.
 */
export const processAxiosError = (
  error: AxiosError & { handled?: boolean },
  { router }: ErrorHandlerDependencies,
): void => {
  if (error.code === "ERR_CONNECTION_REFUSED" || error.code === "ERR_NETWORK") {
    toast.error("Server unreachable. Try again later");
    error.handled = true;
    return;
  }

  if (!error.response) return;

  const { status, data } = error.response;

  switch (status) {
    case 401:
      // Only a genuine auth failure prompts re-login. Integration/permission
      // problems come back as 403, never 401.
      if (getErrorCode(data) === API_ERROR_CODES.NOT_AUTHENTICATED) {
        useLoginModalStore.getState().openModal();
      }
      error.handled = true;
      break;

    case 403:
      handleForbiddenError(data, router);
      error.handled = true;
      break;

    case 402:
      // Only mark this handled — and suppress the fallback error toast —
      // when the body actually is the subscription_required shape. A
      // malformed or unrelated 402 must still reach the caller's default
      // error handling (see service.ts) instead of vanishing silently.
      error.handled = handleSubscriptionRequiredError(data);
      break;

    case 429:
      if (!handleRateLimitError(data)) {
        toast.error("Too many Requests!");
      }
      error.handled = true;
      break;

    default:
      if (status >= 500) {
        toast.error("Server error. Please try again later.");
        error.handled = true;
      }
      break;
  }
};

const handleForbiddenError = (
  errorData: unknown,
  router: AppRouterInstance,
): void => {
  const detail =
    errorData && typeof errorData === "object" && "detail" in errorData
      ? (errorData as { detail: unknown }).detail
      : undefined;

  if (
    typeof detail === "object" &&
    detail !== null &&
    "error_code" in detail &&
    (detail as { error_code: string }).error_code === "UPGRADE_REQUIRED"
  ) {
    return;
  }

  if (
    typeof detail === "object" &&
    detail !== null &&
    "type" in detail &&
    detail.type === "integration"
  ) {
    const integrationDetail = detail as {
      type: string;
      message?: string;
      toolkit?: string;
    };
    const toastKey = `integration-${integrationDetail.toolkit || "default"}`;

    toast.error(integrationDetail.message || "Integration required.", {
      id: toastKey,
      duration: Infinity,
      action: {
        label: "Reconnect",
        onClick: () => {
          router.push("/integrations");
        },
      },
    });
  } else {
    const message =
      typeof detail === "string"
        ? detail
        : "You don't have permission to access this resource.";
    toast.error(message);
  }
};

const SUBSCRIPTION_REQUIRED_CODE = "subscription_required";

interface SubscriptionRequiredDetail {
  code: string;
  message: string;
  checkout_url: string | null;
  discount_code: string | null;
}

/**
 * Extracts the `{ code: "subscription_required", message, checkout_url,
 * discount_code }` payload a 402 response carries under `detail`, or
 * `undefined` if the body isn't shaped that way.
 */
export const getSubscriptionRequiredDetail = (
  data: unknown,
): SubscriptionRequiredDetail | undefined => {
  const detail =
    data && typeof data === "object" && "detail" in data
      ? (data as { detail: unknown }).detail
      : undefined;
  if (
    detail &&
    typeof detail === "object" &&
    "code" in detail &&
    (detail as { code?: unknown }).code === SUBSCRIPTION_REQUIRED_CODE
  ) {
    return detail as SubscriptionRequiredDetail;
  }
  return undefined;
};

/**
 * Maps the `subscription_required` 402 payload onto the paywall store's
 * offer shape. Shared by the axios interceptor (below) and the chat-stream
 * client (`chatApi.ts`, whose 402s never pass through axios) so both open
 * the paywall with the same fields.
 */
export const subscriptionRequiredOfferFromDetail = (
  detail: SubscriptionRequiredDetail,
): PaywallOffer => ({
  checkoutUrl: detail.checkout_url,
  discountCode: detail.discount_code,
  message: detail.message,
});

/**
 * A 402 gated endpoint means the user must subscribe before this action can
 * proceed. Opens the non-dismissible paywall instead of a toast — this is a
 * hard wall, not a transient error. Returns whether the body actually was
 * the subscription_required shape, so the caller can fall back to default
 * error handling for a malformed/unrelated 402 instead of swallowing it.
 */
const handleSubscriptionRequiredError = (errorData: unknown): boolean => {
  const detail = getSubscriptionRequiredDetail(errorData);
  if (!detail) return false;

  usePaywallModalStore
    .getState()
    .openModal(subscriptionRequiredOfferFromDetail(detail));
  return true;
};

/**
 * Renders the rate-limit upsell UI (feature-restricted / rate-limit toast)
 * for a 429 response body. Returns false when the body is not the backend's
 * rate_limit_exceeded shape so callers can fall back to a generic toast.
 * Shared by the axios interceptor and the chat-stream client.
 */
export const handleRateLimitError = (errorData: unknown): boolean => {
  const rateLimitData =
    errorData && typeof errorData === "object" && "detail" in errorData
      ? (errorData as { detail: unknown }).detail
      : undefined;

  if (
    typeof rateLimitData !== "object" ||
    rateLimitData === null ||
    !("error" in rateLimitData) ||
    rateLimitData.error !== "rate_limit_exceeded"
  ) {
    return false;
  }

  const rateLimit = rateLimitData as {
    error: string;
    feature?: string;
    plan_required?: string;
    reset_time?: string;
    message?: string;
    current_plan?: string;
  };

  const { feature, plan_required, reset_time, message, current_plan } =
    rateLimit;
  // A user already on the top tier has nothing to upgrade to — never pitch it.
  const isPro = current_plan === "pro";

  if (plan_required) {
    // Prefer the backend's message (it distinguishes a usage/cost wall from a
    // genuinely plan-gated feature); only fall back to the auto-generated
    // "only available in Pro" copy when no message was sent.
    if (message) {
      showRateLimitToast({
        message,
        planRequired: plan_required,
        resetTime: reset_time,
        feature,
        showUpgradeButton: true,
      });
    } else {
      showFeatureRestrictedToast(
        feature?.replace(/_/g, " ") || "This feature",
        plan_required,
      );
    }
  } else if (feature?.includes("token")) {
    showTokenLimitToast(feature, plan_required);
  } else {
    showRateLimitToast({
      title: "Rate Limit Exceeded",
      message: message || undefined,
      resetTime: reset_time,
      feature,
      showUpgradeButton: !isPro,
    });
  }

  return true;
};
