"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import { Tooltip } from "@heroui/tooltip";
import { useRouter } from "next/navigation";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import {
  convertToUSDCents,
  formatUSDFromCents,
} from "@/features/pricing/utils/currencyConverter";
import {
  SettingsPage,
  SettingsRow,
  SettingsSection,
} from "@/features/settings/components/ui";

const formatDate = (dateString?: string): string => {
  if (!dateString) return "N/A";
  try {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return "N/A";
  }
};

const getDaysUntil = (dateString?: string): number | null => {
  if (!dateString) return null;
  try {
    const diff = new Date(dateString).getTime() - Date.now();
    const days = Math.ceil(diff / (1000 * 60 * 60 * 24));
    return days > 0 ? days : 0;
  } catch {
    return null;
  }
};

type ChipColor = "success" | "warning" | "danger" | "default";

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

export function SubscriptionSettings() {
  const { data: status, isLoading } = useUserSubscriptionStatus();
  const router = useRouter();

  const handleUpgrade = () => router.push("/pricing");

  if (isLoading) {
    return (
      <SettingsPage>
        <SettingsSection title="Plan">
          <div className="space-y-3 px-4 py-3.5">
            <Skeleton className="h-4 w-32 rounded-lg" />
            <Skeleton className="h-4 w-64 rounded-lg" />
            <Skeleton className="h-4 w-48 rounded-lg" />
          </div>
        </SettingsSection>
      </SettingsPage>
    );
  }

  if (!status?.is_subscribed) {
    return (
      <SettingsPage>
        {/* Plan summary header */}
        <div className="rounded-2xl bg-zinc-900/60 px-5 py-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                Current Plan
              </p>
              <p className="mt-1 text-2xl font-semibold text-white">Free</p>
            </div>
            <Chip color="success" variant="flat" size="sm" className="text-xs">
              Active
            </Chip>
          </div>
          <p className="mt-1 text-sm text-zinc-500">
            Forever free · No billing
          </p>
        </div>

        <SettingsSection title="Upgrade to Pro">
          <div className="px-4 py-4 space-y-3">
            <p className="text-sm text-zinc-400">
              Unlock unlimited usage and all features. Get 25–250× higher
              limits, priority support, and private Discord channels.
            </p>
            <Button
              color="primary"
              className="w-full font-semibold text-black"
              size="sm"
              onPress={handleUpgrade}
            >
              View plans
            </Button>
          </div>
        </SettingsSection>
      </SettingsPage>
    );
  }

  const plan = status.current_plan;
  const subscription = status.subscription;

  const priceFormatted = (() => {
    if (plan) {
      return formatUSDFromCents(convertToUSDCents(plan.amount, plan.currency));
    }
    if (subscription?.recurring_pre_tax_amount) {
      return formatUSDFromCents(subscription.recurring_pre_tax_amount);
    }
    return "$0";
  })();

  const billingCycle = (() => {
    if (plan?.duration) return plan.duration;
    const interval = subscription?.payment_frequency_interval?.toLowerCase();
    if (interval === "month") return "monthly";
    if (interval === "year") return "yearly";
    return interval || "monthly";
  })();

  const planName =
    plan?.name || (status.plan_type === "pro" ? "GAIA Pro" : "GAIA Free");

  const daysUntilNextBilling = getDaysUntil(subscription?.next_billing_date);
  const statusColor = getStatusColor(subscription?.status || "unknown");
  const statusText = getStatusText(subscription?.status || "unknown");

  const nextBillingLabel = (() => {
    if (daysUntilNextBilling === null) return null;
    if (daysUntilNextBilling === 0) return "due today";
    if (daysUntilNextBilling === 1) return "tomorrow";
    return `in ${daysUntilNextBilling} days`;
  })();

  return (
    <SettingsPage>
      {/* Plan summary header */}
      <div className="rounded-2xl bg-zinc-900/60 px-5 py-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
              Current Plan
            </p>
            <p className="mt-1 text-2xl font-semibold text-white">{planName}</p>
            {plan?.description && (
              <p className="mt-0.5 text-sm text-zinc-500">{plan.description}</p>
            )}
          </div>
          <Chip
            color={statusColor}
            variant="flat"
            size="sm"
            className="mt-1 text-xs"
          >
            {statusText}
          </Chip>
        </div>
        <p className="mt-3 text-sm text-zinc-400">
          {priceFormatted}{" "}
          <span className="text-zinc-600">/ {billingCycle}</span>
          {nextBillingLabel && (
            <span className="ml-3 text-xs text-zinc-600">
              Next billing {nextBillingLabel}
            </span>
          )}
        </p>
      </div>

      {/* Billing details */}
      <SettingsSection title="Billing">
        <SettingsRow label="Billing cycle">
          <span className="text-sm capitalize text-zinc-300">
            {billingCycle}
          </span>
        </SettingsRow>

        {subscription?.next_billing_date && (
          <SettingsRow
            label="Next billing date"
            description={nextBillingLabel ?? undefined}
          >
            <span className="text-sm text-zinc-300">
              {formatDate(subscription.next_billing_date)}
            </span>
          </SettingsRow>
        )}

        {subscription?.previous_billing_date && (
          <SettingsRow label="Last payment">
            <span className="text-sm text-zinc-300">
              {formatDate(subscription.previous_billing_date)}
            </span>
          </SettingsRow>
        )}

        {subscription?.created_at && (
          <SettingsRow label="Subscribed since">
            <span className="text-sm text-zinc-300">
              {formatDate(subscription.created_at)}
            </span>
          </SettingsRow>
        )}

        {subscription?.cancelled_at && (
          <SettingsRow label="Cancelled on">
            <span className="text-sm text-red-400">
              {formatDate(subscription.cancelled_at)}
            </span>
          </SettingsRow>
        )}

        {subscription?.dodo_subscription_id && (
          <SettingsRow
            label="Subscription ID"
            description="For support queries"
          >
            <span
              className="font-mono text-sm text-zinc-500"
              title={subscription.dodo_subscription_id}
            >
              ···{subscription.dodo_subscription_id.slice(-8)}
            </span>
          </SettingsRow>
        )}
      </SettingsSection>

      {/* Plan features */}
      {plan?.features && plan.features.length > 0 && (
        <SettingsSection title="What's included">
          <div className="px-4 py-3.5">
            <ul className="space-y-2">
              {plan.features.map((feature) => (
                <li
                  key={feature}
                  className="flex items-start gap-2 text-sm text-zinc-400"
                >
                  <span className="mt-0.5 text-emerald-400">✓</span>
                  <span>{feature}</span>
                </li>
              ))}
            </ul>
          </div>
        </SettingsSection>
      )}

      {/* Actions */}
      <SettingsSection title="Actions">
        <div className="space-y-2 px-4 py-3.5">
          <Button
            color="primary"
            variant="flat"
            onPress={handleUpgrade}
            size="sm"
            className="w-full"
          >
            View plans
          </Button>

          {subscription?.status === "active" && (
            <Tooltip content="Please contact support to cancel your subscription for now">
              <Button
                color="danger"
                variant="light"
                isDisabled
                size="sm"
                className="w-full"
              >
                Cancel subscription
              </Button>
            </Tooltip>
          )}
        </div>
      </SettingsSection>
    </SettingsPage>
  );
}
