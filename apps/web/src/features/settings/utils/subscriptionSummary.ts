import type { UserSubscriptionStatus } from "@/features/pricing/api/pricingApi";
import {
  convertToUSDCents,
  formatUSDFromCents,
} from "@/features/pricing/utils/currencyConverter";

// Module-scope formatter: hoisting keeps locale resolution out of the render
// path (js-hoist-intl); explicit locale+timeZone gives deterministic
// server/browser text per no-locale-format-in-render. Billing days are
// rendered as UTC calendar dates.
const BILLING_DATE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "long",
  day: "numeric",
  timeZone: "UTC",
});

export const formatDate = (dateString?: string): string => {
  if (!dateString) return "N/A";
  try {
    // Deterministic UTC billing dates — see formatter comment above.
    return BILLING_DATE_FORMATTER.format(new Date(dateString));
  } catch {
    return "N/A";
  }
};

const MS_PER_DAY = 1000 * 60 * 60 * 24;

const getDaysUntil = (dateString?: string): number | null => {
  if (!dateString) return null;
  try {
    const diff = new Date(dateString).getTime() - Date.now();
    return Math.ceil(diff / MS_PER_DAY);
  } catch {
    return null;
  }
};

export type ChipColor = "success" | "warning" | "danger" | "default";

function getStatusColor(status: string): ChipColor {
  switch (status.toLowerCase()) {
    case "active":
      return "success";
    case "created":
    case "on_hold":
      return "warning";
    case "cancelled":
    case "expired":
      return "danger";
    default:
      return "default";
  }
}

function getStatusText(status: string): string {
  switch (status.toLowerCase()) {
    case "created":
      return "Activating";
    case "active":
      return "Active";
    case "cancelled":
      return "Cancelled";
    case "expired":
      return "Expired";
    case "on_hold":
      return "On Hold";
    default:
      return status;
  }
}

function getPriceFormatted(status: UserSubscriptionStatus): string {
  const plan = status.current_plan;
  if (plan) {
    return formatUSDFromCents(convertToUSDCents(plan.amount, plan.currency));
  }
  const preTaxAmount = status.subscription?.recurring_pre_tax_amount;
  if (preTaxAmount) return formatUSDFromCents(preTaxAmount);
  return "$0";
}

function getBillingCycle(status: UserSubscriptionStatus): string {
  if (status.current_plan?.duration) return status.current_plan.duration;
  const interval =
    status.subscription?.payment_frequency_interval?.toLowerCase();
  if (interval === "month") return "monthly";
  if (interval === "year") return "yearly";
  return interval || "monthly";
}

/** How soon the next charge lands, in the words the settings page uses. */
function getNextBillingLabel(nextBillingDate?: string): string | null {
  const daysUntilNextBilling = getDaysUntil(nextBillingDate);
  if (daysUntilNextBilling === null) return null;
  if (daysUntilNextBilling < 0) return "overdue";
  if (daysUntilNextBilling === 0) return "due today";
  if (daysUntilNextBilling === 1) return "tomorrow";
  return `in ${daysUntilNextBilling} days`;
}

/** Everything the active-subscription view renders, derived in one place. */
export interface SubscriptionSummary {
  planName: string;
  priceFormatted: string;
  billingCycle: string;
  statusColor: ChipColor;
  statusText: string;
  cancellationScheduled: boolean;
  nextBillingLabel: string | null;
}

export function getSubscriptionSummary(
  status: UserSubscriptionStatus,
): SubscriptionSummary {
  const subscription = status.subscription;
  const cancellationScheduled =
    subscription?.cancel_at_next_billing_date === true;

  return {
    planName:
      status.current_plan?.name ||
      (status.plan_type === "pro" ? "GAIA Pro" : "GAIA Free"),
    priceFormatted: getPriceFormatted(status),
    billingCycle: getBillingCycle(status),
    statusColor: cancellationScheduled
      ? "warning"
      : getStatusColor(subscription?.status || "unknown"),
    statusText: cancellationScheduled
      ? "Cancelling"
      : getStatusText(subscription?.status || "unknown"),
    cancellationScheduled,
    nextBillingLabel: getNextBillingLabel(subscription?.next_billing_date),
  };
}
