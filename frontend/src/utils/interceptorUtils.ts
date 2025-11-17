import { AxiosError } from "axios";
import { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { toast } from "sonner";

import {
  showFeatureRestrictedToast,
  showRateLimitToast,
  showTokenLimitToast,
} from "@/components/shared/RateLimitToast";
import { useLoginModalStore } from "@/stores/loginModalStore";

// Types
interface ErrorHandlerDependencies {
  router: AppRouterInstance;
}

// Track active integration toasts to prevent duplicates
const activeIntegrationToasts = new Set<string>();

// Constants
const LANDING_ROUTES = [
  "/",
  "/terms",
  "/privacy",
  "/login",
  "/signup",
  "/contact",
  "/manifesto",
  "/blog",
  "/pricing",
];

// Utility functions
export const isOnLandingRoute = (pathname: string): boolean => {
  return LANDING_ROUTES.includes(pathname) || pathname.startsWith("/blog/");
};

// Main error processor
export const processAxiosError = (
  error: AxiosError,
  pathname: string,
  { router }: ErrorHandlerDependencies,
): void => {
  console.error("Axios Error:", error, "Pathname:", pathname);

  // Skip error handling on landing pages
  if (isOnLandingRoute(pathname)) {
    return;
  }

  // Handle network errors
  if (error.code === "ERR_CONNECTION_REFUSED" || error.code === "ERR_NETWORK") {
    toast.error("Server unreachable. Try again later");
    return;
  }

  // Handle HTTP errors
  if (error.response) {
    const { status, data } = error.response;

    switch (status) {
      case 401:
        useLoginModalStore.getState().openModal();
        break;

      case 403:
        handleForbiddenError(data, router);
        break;

      case 429:
        toast.error("Too many Requests!");
        handleRateLimitError(data);
        break;

      default:
        if (status >= 500) {
          toast.error("Server error. Please try again later.");
        }
        break;
    }
  }
};

// Handle 403 Forbidden errors
const handleForbiddenError = (
  errorData: unknown,
  router: AppRouterInstance,
): void => {
  // Safely extract detail from unknown error data structure
  const detail =
    errorData && typeof errorData === "object" && "detail" in errorData
      ? (errorData as { detail: unknown }).detail
      : undefined;

  // Handle integration errors with redirect action
  if (
    typeof detail === "object" &&
    detail !== null &&
    "type" in detail &&
    detail.type === "integration"
  ) {
    const integrationDetail = detail as { type: string; message?: string };
    const toastKey = `integration-${integrationDetail.type || "default"}`;

    // Check if toast for this integration is already active
    if (activeIntegrationToasts.has(toastKey)) {
      return;
    }

    // Add to active toasts set
    activeIntegrationToasts.add(toastKey);

    toast.error(integrationDetail.message || "Integration required.", {
      duration: Infinity,
      classNames: {
        actionButton: "bg-red-500/30! py-4! px-3!",
      },
      action: {
        label: "Connect",
        onClick: () => {
          // Clear from active toasts when action is clicked
          activeIntegrationToasts.delete(toastKey);
          router.push("/settings?section=integrations");
        },
      },
      onDismiss: () => {
        // Clear from active toasts when dismissed
        activeIntegrationToasts.delete(toastKey);
      },
    });
  } else {
    // Handle generic forbidden errors
    const message =
      typeof detail === "string"
        ? detail
        : "You don't have permission to access this resource.";
    toast.error(message);
  }
};

// Handle 429 Rate Limit errors
const handleRateLimitError = (errorData: unknown): void => {
  // Safely extract rate limit data from unknown error data structure
  const rateLimitData =
    errorData && typeof errorData === "object" && "detail" in errorData
      ? (errorData as { detail: unknown }).detail
      : undefined;

  // Validate rate limit error structure
  if (
    typeof rateLimitData !== "object" ||
    rateLimitData === null ||
    !("error" in rateLimitData) ||
    rateLimitData.error !== "rate_limit_exceeded"
  ) {
    return;
  }

  // Type-safe extraction of rate limit properties
  const rateLimit = rateLimitData as {
    error: string;
    feature?: string;
    plan_required?: string;
    reset_time?: string;
    message?: string;
  };

  const { feature, plan_required, reset_time, message } = rateLimit;

  if (plan_required) {
    showFeatureRestrictedToast(feature || "This feature", plan_required);
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
};
