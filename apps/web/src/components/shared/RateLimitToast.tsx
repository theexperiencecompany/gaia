"use client";

import { Alert01Icon, CheckmarkBadge01Icon, Timer02Icon } from "@icons";
import { formatPlanName } from "@shared/utils";
import type { ReactNode } from "react";
import { toast } from "@/lib/toast";
import { usePricingModalStore } from "@/stores/pricingModalStore";

interface ToastConfig {
  duration: number;
  icon: ReactNode;
  action?: {
    label: string;
    onClick: () => void;
  };
}

interface RateLimitToastProps {
  title?: string;
  message?: string;
  showUpgradeButton?: boolean;
  resetTime?: string;
  feature?: string;
  planRequired?: string;
}

function buildResetMessage(resetTime: string): string {
  const resetDate = new Date(resetTime);
  const now = new Date();
  const timeDiff = Math.ceil(
    (resetDate.getTime() - now.getTime()) / (1000 * 60),
  ); // minutes

  if (timeDiff > 60) {
    const hours = Math.ceil(timeDiff / 60);
    return `Rate limit exceeded. Resets in ${hours} hour${hours > 1 ? "s" : ""}.`;
  }
  if (timeDiff > 0) {
    return `Rate limit exceeded. Resets in ${timeDiff} minute${timeDiff > 1 ? "s" : ""}.`;
  }
  return "Rate limit exceeded. Resets very soon.";
}

function buildRateLimitMessage({
  isUpgradeRequired,
  feature,
  planName,
  resetTime,
}: {
  isUpgradeRequired: boolean;
  feature?: string;
  planName?: string;
  resetTime?: string;
}): string {
  if (isUpgradeRequired) {
    return `${feature || "This feature"} is only available in the ${planName} plan. Upgrade to continue using it.`;
  }
  if (resetTime) {
    return buildResetMessage(resetTime);
  }
  return "You've exceeded the rate limit. Please upgrade for higher limits.";
}

export const showRateLimitToast = ({
  title = "Rate Limit Reached",
  message,
  showUpgradeButton = true,
  resetTime,
  feature,
  planRequired,
}: RateLimitToastProps = {}) => {
  // Determine the appropriate icon and styling based on error type
  const isUpgradeRequired = Boolean(planRequired && showUpgradeButton);
  const Icon = isUpgradeRequired
    ? CheckmarkBadge01Icon
    : resetTime
      ? Timer02Icon
      : Alert01Icon;

  const planName = planRequired ? formatPlanName(planRequired) : undefined;

  // Auto-generate message if not provided
  if (!message) {
    message = buildRateLimitMessage({
      isUpgradeRequired,
      feature,
      planName,
      resetTime,
    });
  }

  const toastConfig: ToastConfig = {
    duration: isUpgradeRequired ? 10000 : 8000, // Longer duration for upgrade prompts
    icon: (
      <Icon
        className={isUpgradeRequired ? "text-yellow-500" : "text-red-500"}
        size={20}
      />
    ),
  };

  // Add upgrade action if needed
  if (showUpgradeButton) {
    toastConfig.action = {
      label: isUpgradeRequired ? `Upgrade to ${planName}` : "Upgrade Now",
      onClick: () => usePricingModalStore.getState().openModal(),
    };
  }

  toast.error(`${title}: ${message}`, toastConfig);
};

// Specific toast functions for different scenarios
export const showFeatureRestrictedToast = (
  feature: string,
  planRequired: string,
) => {
  showRateLimitToast({
    title: "Feature Restricted",
    feature,
    planRequired,
    showUpgradeButton: true,
  });
};

export const showTokenLimitToast = (feature: string, planRequired?: string) => {
  showRateLimitToast({
    title: "Token Limit Exceeded",
    message: planRequired
      ? `${feature} token limit exceeded. Upgrade to ${formatPlanName(planRequired)} for higher token limits.`
      : `${feature} token limit exceeded. Please wait or upgrade for higher limits.`,
    planRequired,
    showUpgradeButton: !!planRequired,
  });
};
