"use client";

import { ReactNode } from "react";
import { toast } from "sonner";

import { Alert01Icon, CheckmarkBadge01Icon,Timer02Icon } from '@/icons';

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

export const showRateLimitToast = ({
  title = "Rate Limit Reached",
  message,
  showUpgradeButton = true,
  resetTime,
  feature,
  planRequired,
}: RateLimitToastProps = {}) => {
  // Determine the appropriate icon and styling based on error type
  const isUpgradeRequired = planRequired && showUpgradeButton;
  const Icon = isUpgradeRequired ? CheckmarkBadge01Icon : resetTime ? Timer02Icon : Alert01Icon;

  // Auto-generate message if not provided
  if (!message) {
    if (isUpgradeRequired) {
      message = `${feature || "This feature"} is only available in the ${planRequired.toUpperCase()} plan. Upgrade to continue using it.`;
    } else if (resetTime) {
      const resetDate = new Date(resetTime);
      const now = new Date();
      const timeDiff = Math.ceil(
        (resetDate.getTime() - now.getTime()) / (1000 * 60),
      ); // minutes

      if (timeDiff > 60) {
        const hours = Math.ceil(timeDiff / 60);
        message = `Rate limit exceeded. Resets in ${hours} hour${hours > 1 ? "s" : ""}.`;
      } else if (timeDiff > 0) {
        message = `Rate limit exceeded. Resets in ${timeDiff} minute${timeDiff > 1 ? "s" : ""}.`;
      } else {
        message = "Rate limit exceeded. Resets very soon.";
      }
    } else {
      message =
        "You've exceeded the rate limit. Please upgrade for higher limits.";
    }
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
      label: isUpgradeRequired
        ? `Upgrade to ${planRequired?.toUpperCase()}`
        : "Upgrade Now",
      onClick: () => {
        window.location.href = "/pricing";
      },
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

export const showRateLimitExceededToast = (
  feature: string,
  resetTime?: string,
) => {
  showRateLimitToast({
    title: "Rate Limit Exceeded",
    feature,
    resetTime,
    showUpgradeButton: true,
  });
};

export const showTokenLimitToast = (feature: string, planRequired?: string) => {
  showRateLimitToast({
    title: "Token Limit Exceeded",
    message: planRequired
      ? `${feature} token limit exceeded. Upgrade to ${planRequired.toUpperCase()} for higher token limits.`
      : `${feature} token limit exceeded. Please wait or upgrade for higher limits.`,
    planRequired,
    showUpgradeButton: !!planRequired,
  });
};
