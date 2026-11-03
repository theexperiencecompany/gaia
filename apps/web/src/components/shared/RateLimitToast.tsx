"use client";

import { Alert01Icon, CheckmarkBadge01Icon, Timer02Icon } from "@icons";
import { formatDate, formatPlanName } from "@shared/utils";
import type { ReactNode } from "react";
import { toast } from "@/lib/toast";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

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

const MINUTES_PER_DAY = 24 * 60;

function minutesUntil(resetTime: string): number {
  return Math.ceil((new Date(resetTime).getTime() - Date.now()) / (1000 * 60));
}

function resetsIn(resetTime: string): string {
  const minutes = minutesUntil(resetTime);

  // A monthly pause is days away: name the day instead of counting hours.
  if (minutes > MINUTES_PER_DAY) {
    return `Resets on ${formatDate(resetTime)}.`;
  }
  if (minutes > 60) {
    const hours = Math.ceil(minutes / 60);
    return `Resets in ${hours} hour${hours > 1 ? "s" : ""}.`;
  }
  if (minutes > 0) {
    return `Resets in ${minutes} minute${minutes > 1 ? "s" : ""}.`;
  }
  return "Resets very soon.";
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
    return `Rate limit exceeded. ${resetsIn(resetTime)}`;
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

  // A multi-day pause names its reset day in the server's own message; a same-day
  // one gets the countdown here, which only the client can phrase.
  if (!message) {
    message = buildRateLimitMessage({
      isUpgradeRequired,
      feature,
      planName,
      resetTime,
    });
  } else if (
    resetTime &&
    !isUpgradeRequired &&
    minutesUntil(resetTime) <= MINUTES_PER_DAY
  ) {
    message = `${message} ${resetsIn(resetTime)}`;
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
      onClick: () =>
        useUpgradeModalStore.getState().openModal(undefined, {
          dismissible: true,
          source: "rate_limit_toast",
        }),
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
