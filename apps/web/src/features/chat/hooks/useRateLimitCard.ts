import type { RateLimitData } from "@shared/chat";
import {
  formatFeatureName,
  formatPlanName,
  rateLimitResetInfo,
} from "@shared/utils";

import { useDeployment } from "@/features/settings/hooks/useSetupStatus";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

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
  const billingEnabled = useDeployment().bills;
  const isUpgradeRequired = !!plan_required;
  // Nothing to upgrade to on the top tier, nor where nothing is sold.
  const showUpgradeNudge = billingEnabled && current_plan !== "pro";
  const resetInfo = rateLimitResetInfo(reset_time);
  const featureName = formatFeatureName(feature);
  const planName = formatPlanName(plan_required);
  // The footer is either an "Upgrade to X" CTA or a neutral "View Plans" link.
  // A pro user hitting a daily cap has nothing to upgrade to, so the neutral
  // link is noise — drop the whole footer for them.
  const showFooter = billingEnabled && (isUpgradeRequired || showUpgradeNudge);

  const openPlans = () =>
    openUpgradeModal(undefined, {
      dismissible: true,
      source: "rate_limit_card",
    });

  return {
    message,
    isUpgradeRequired,
    showUpgradeNudge,
    resetInfo,
    featureName,
    planName,
    showFooter,
    subtitle: getSubtitle(message, current_plan, isUpgradeRequired, planName),
    openPlans,
  };
}
