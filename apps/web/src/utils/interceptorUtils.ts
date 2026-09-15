import type { SubscriptionRequiredDetail } from "@shared/types/subscription";
import { getSubscriptionRequiredDetail } from "@shared/types/subscription";
import type { AxiosError } from "axios";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";

import {
  showFeatureRestrictedToast,
  showRateLimitToast,
  showTokenLimitToast,
} from "@/components/shared/RateLimitToast";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";
import { getErrorCode, getErrorMessage } from "@/lib/api/errors";
import { toast } from "@/lib/toast";
import { useLoginModalStore } from "@/stores/loginModalStore";
import type { UpgradeOffer } from "@/stores/upgradeModal.types";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

interface ErrorHandlerDependencies {
  router: AppRouterInstance;
}

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
  const code = getErrorCode(errorData);
  const message = getErrorMessage(errorData);

  if (code === "UPGRADE_REQUIRED") {
    return;
  }

  if (code === API_ERROR_CODES.INTEGRATION_NOT_CONNECTED) {
    const { toolkit } = errorData as { toolkit?: string };
    toast.error(message || "Integration required.", {
      id: `integration-${toolkit || "default"}`,
      duration: Infinity,
      action: {
        label: "Reconnect",
        onClick: () => {
          router.push("/integrations");
        },
      },
    });
  } else {
    toast.error(
      message || "You don't have permission to access this resource.",
    );
  }
};

/**
 * Maps the `subscription_required` 402 payload onto the paywall store's
 * offer shape. Shared by the axios interceptor (below) and the chat-stream
 * client (`chatApi.ts`, whose 402s never pass through axios) so both open
 * the paywall with the same fields.
 */
export const subscriptionRequiredOfferFromDetail = (
  detail: SubscriptionRequiredDetail,
): UpgradeOffer => ({
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

  useUpgradeModalStore
    .getState()
    .openModal(subscriptionRequiredOfferFromDetail(detail), {
      source: "api_402",
    });
  return true;
};

/**
 * Renders the rate-limit upsell UI (feature-restricted / rate-limit toast)
 * for a 429 response body. Returns false when the body is not the backend's
 * rate_limit_exceeded shape so callers can fall back to a generic toast.
 * Shared by the axios interceptor and the chat-stream client.
 */
export const handleRateLimitError = (errorData: unknown): boolean => {
  if (getErrorCode(errorData) !== "rate_limit_exceeded") {
    return false;
  }

  const rateLimit = errorData as {
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
