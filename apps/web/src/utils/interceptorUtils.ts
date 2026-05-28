import type { AxiosError } from "axios";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";

import {
  showFeatureRestrictedToast,
  showRateLimitToast,
  showTokenLimitToast,
} from "@/components/shared/RateLimitToast";
import { toast } from "@/lib/toast";
import { useLoginModalStore } from "@/stores/loginModalStore";

interface ErrorHandlerDependencies {
  router: AppRouterInstance;
}

/**
 * Surfaces API error UI for app-shell requests: toasts on 5xx/429/403,
 * login modal on 401. Only mounted inside the (main) provider tree —
 * landing pages never surface background-fetch errors because anonymous
 * visitors should not be interrupted by UI they did not trigger.
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
      useLoginModalStore.getState().openModal();
      error.handled = true;
      break;

    case 403:
      handleForbiddenError(data, router);
      error.handled = true;
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
    const integrationDetail = detail as { type: string; message?: string };
    const toastKey = `integration-${integrationDetail.type || "default"}`;

    toast.error(integrationDetail.message || "Integration required.", {
      id: toastKey,
      duration: Infinity,
      action: {
        label: "Connect",
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

const handleRateLimitError = (errorData: unknown): boolean => {
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
  };

  const { feature, plan_required, reset_time, message } = rateLimit;

  if (plan_required) {
    showFeatureRestrictedToast(
      feature?.replace("_", " ") || "This feature",
      plan_required,
    );
  } else if (feature?.includes("token")) {
    showTokenLimitToast(feature, plan_required);
  } else {
    showRateLimitToast({
      title: "Rate Limit Exceeded",
      message: message || undefined,
      resetTime: reset_time,
      feature,
      showUpgradeButton: true,
    });
  }

  return true;
};
