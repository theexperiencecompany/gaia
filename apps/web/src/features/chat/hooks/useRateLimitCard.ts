import type { RateLimitData } from "@shared/chat";
import { formatFeatureName, formatPlanName } from "@shared/utils";

import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

function getResetInfo(
  resetTime?: string,
): { label: string; detail: string } | null {
  if (!resetTime) return null;
  const reset = new Date(resetTime);
  const diffMs = reset.getTime() - Date.now();
  if (diffMs <= 0)
    return {
      label: "Resets very soon",
      detail: "Your limit will refresh shortly.",
    };
  const diffMins = Math.ceil(diffMs / 60000);
  if (diffMins > 60) {
    const hours = Math.ceil(diffMins / 60);
    return {
      label: `Resets in ${hours} hour${hours !== 1 ? "s" : ""}`,
      detail: `Available again at ${reset.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
    };
  }
  return {
    label: `Resets in ${diffMins} minute${diffMins !== 1 ? "s" : ""}`,
    detail: `Available again at ${reset.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
  };
}

function getSubtitle(
  message: string | undefined,
  currentPlan: string | undefined,
  isUpgradeRequired: boolean,
  planName: string,
): string {
  if (message)
    return `${formatPlanName(currentPlan ?? "free")} plan limit reached`;
  if (isUpgradeRequired) return `Requires ${planName} plan`;
  return "Daily limit reached";
}

/** Everything the rate-limit card renders is derived from one payload. */
export function useRateLimitCard(data: RateLimitData) {
  const { feature, plan_required, reset_time, message, current_plan } = data;
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);
  const isUpgradeRequired = !!plan_required;
  // A user already on the top tier has nothing to upgrade to — hide the pitch.
  const isPro = current_plan === "pro";
  const resetInfo = getResetInfo(reset_time);
  const featureName = formatFeatureName(feature);
  const planName = formatPlanName(plan_required);
  // The footer is either an "Upgrade to X" CTA or a neutral "View Plans" link.
  // A pro user hitting a daily cap has nothing to upgrade to, so the neutral
  // link is noise — drop the whole footer for them.
  const showFooter = isUpgradeRequired || !isPro;

  const openPlans = () =>
    openUpgradeModal(undefined, {
      dismissible: true,
      source: "rate_limit_card",
    });

  return {
    message,
    isUpgradeRequired,
    isPro,
    resetInfo,
    featureName,
    planName,
    showFooter,
    subtitle: getSubtitle(message, current_plan, isUpgradeRequired, planName),
    openPlans,
  };
}
