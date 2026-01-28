"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import { Tooltip } from "@heroui/tooltip";
import Image from "next/image";
import { useRouter } from "next/navigation";

import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import {
  convertToUSDCents,
  formatUSDFromCents,
} from "@/features/pricing/utils/currencyConverter";
import { SettingsCard } from "@/features/settings/components/SettingsCard";
import { Calendar03Icon, CreditCardIcon } from "@/icons";

/**
 * Formats a date string to a human-readable format
 */
const formatDate = (dateString?: string): string => {
  if (!dateString) return "N/A";
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return "N/A";
  }
};

/**
 * Calculates days until a future date
 */
const getDaysUntil = (dateString?: string): number | null => {
  if (!dateString) return null;
  try {
    const targetDate = new Date(dateString);
    const today = new Date();
    const diffTime = targetDate.getTime() - today.getTime();
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays > 0 ? diffDays : 0;
  } catch {
    return null;
  }
};

export function SubscriptionSettings() {
  const { data: subscriptionStatus, isLoading } = useUserSubscriptionStatus();
  const router = useRouter();

  const handleUpgrade = () => {
    router.push("/pricing");
  };

  if (isLoading) {
    return (
      <SettingsCard
        icon={<CreditCardIcon className="h-5 w-5 text-blue-400" />}
        title="Subscription"
      >
        <div className="space-y-4">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-4 w-64" />
          <Skeleton className="h-16 w-full" />
        </div>
      </SettingsCard>
    );
  }

  // Free plan display - only show if NOT subscribed
  if (!subscriptionStatus?.is_subscribed) {
    return (
      <SettingsCard
        icon={<CreditCardIcon className="h-5 w-5 text-primary" />}
        title="Subscription"
      >
        <div className="flex flex-col items-start gap-4 sm:flex-row">
          <div className="relative w-full flex-1 overflow-hidden rounded-2xl bg-zinc-800/40 p-6 backdrop-blur-xl">
            <div className="flex h-full w-full flex-col gap-4">
              {/* Header */}
              <div className="flex flex-row items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-2xl font-semibold text-white">
                    Free
                  </span>
                  <Chip
                    className="flex items-center gap-0.5 text-xs"
                    color="success"
                    variant="flat"
                  >
                    <span>Current Plan</span>
                  </Chip>
                </div>
              </div>

              {/* Price Section */}
              <div className="flex flex-col gap-2">
                <div className="flex items-baseline gap-2">
                  <span className="text-5xl font-bold text-white">$0</span>
                  <span className="text-2xl text-zinc-400">USD</span>
                </div>
                <span className="min-h-5 text-sm font-normal text-zinc-400">
                  Forever free
                </span>
              </div>

              {/* Plan Information */}
              <div className="mt-2 flex-1 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Status</span>
                  <span className="font-sm text-sm text-white">Active</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Billing</span>
                  <span className="font-sm text-sm text-white">None</span>
                </div>
              </div>

              {/* Action Button */}
              <div className="space-y-3">
                <Button
                  color="primary"
                  className="w-full font-semibold text-black"
                  onPress={handleUpgrade}
                >
                  Upgrade to Pro
                </Button>
              </div>
            </div>
          </div>
          <div className="relative h-76 w-full flex-1 overflow-hidden rounded-2xl bg-zinc-800/40 p-0 backdrop-blur-xl">
            <Image
              fill
              src="/images/wallpapers/field.webp"
              alt="Subscription illustration"
              className="h-full w-full object-cover"
            />
          </div>
        </div>
      </SettingsCard>
    );
  }

  // Get plan and subscription data
  const plan = subscriptionStatus.current_plan;
  const subscription = subscriptionStatus.subscription;

  // Derive price from plan or subscription data
  const getPriceFormatted = () => {
    if (plan) {
      const priceInUSDCents = convertToUSDCents(plan.amount, plan.currency);
      return formatUSDFromCents(priceInUSDCents);
    }
    // Fallback to subscription's recurring amount (already in cents for USD)
    if (subscription?.recurring_pre_tax_amount) {
      return formatUSDFromCents(subscription.recurring_pre_tax_amount);
    }
    return "$0";
  };

  const priceFormatted = getPriceFormatted();

  // Derive billing cycle from plan or subscription
  const getBillingCycle = () => {
    if (plan?.duration) return plan.duration;
    if (subscription?.payment_frequency_interval) {
      const interval = subscription.payment_frequency_interval.toLowerCase();
      if (interval === "month") return "monthly";
      if (interval === "year") return "yearly";
      return interval;
    }
    return "monthly";
  };

  const billingCycle = getBillingCycle();

  // Get plan name - fallback to plan_type if no plan object
  const planName =
    plan?.name ||
    (subscriptionStatus.plan_type === "pro" ? "GAIA Pro" : "GAIA Free");

  // Calculate days until next billing
  const daysUntilNextBilling = getDaysUntil(subscription?.next_billing_date);

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case "active":
        return "success";
      case "created":
        return "warning";
      case "cancelled":
      case "expired":
        return "danger";
      case "on_hold":
        return "warning";
      default:
        return "default";
    }
  };

  const getStatusText = (status: string) => {
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
  };

  return (
    <SettingsCard
      icon={<CreditCardIcon className="h-5 w-5 text-blue-400" />}
      title="Subscription"
    >
      <div className="flex flex-col gap-4 lg:flex-row">
        {/* Main Subscription Card */}
        <div className="relative w-full overflow-hidden rounded-2xl bg-zinc-800/40 p-6 backdrop-blur-xl lg:flex-1">
          <div className="flex h-full flex-col gap-4">
            {/* Header */}
            <div className="flex flex-row items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-2xl font-semibold text-white">
                  {planName}
                </span>
                <Chip
                  color={getStatusColor(subscription?.status || "unknown")}
                  variant="flat"
                  size="sm"
                  className="text-xs"
                >
                  {getStatusText(subscription?.status || "unknown")}
                </Chip>
              </div>
            </div>

            {/* Price Section */}
            <div className="flex flex-col gap-0">
              <div className="flex items-baseline gap-2">
                <span className="text-5xl font-bold text-white">
                  {priceFormatted}
                </span>
                <span className="text-2xl text-zinc-400">
                  {subscription?.currency || "USD"}
                </span>
              </div>
              <span className="min-h-5 text-sm font-normal text-zinc-400">
                / per {billingCycle}
              </span>
            </div>

            {/* Plan Information */}
            <div className="mt-2 flex-1 space-y-3">
              {plan?.description && (
                <div className="mb-3 text-sm text-zinc-300">
                  {plan.description}
                </div>
              )}

              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Billing Cycle</span>
                <span className="font-medium capitalize text-white">
                  {billingCycle}
                </span>
              </div>

              {subscription?.next_billing_date && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Next Billing</span>
                  <span className="font-medium text-white">
                    {formatDate(subscription.next_billing_date)}
                  </span>
                </div>
              )}

              {daysUntilNextBilling !== null && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Days Remaining</span>
                  <span className="font-medium text-white">
                    {daysUntilNextBilling} days
                  </span>
                </div>
              )}

              {subscription?.created_at && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Member Since</span>
                  <span className="font-medium text-white">
                    {formatDate(subscription.created_at)}
                  </span>
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className="space-y-3">
              <Button
                color="primary"
                variant="flat"
                onPress={handleUpgrade}
                className="w-full"
              >
                View Plans
              </Button>

              {subscription?.status === "active" && (
                <Tooltip content="Please contact support to cancel your subscription for now">
                  <Button
                    color="danger"
                    variant="light"
                    isDisabled
                    className="w-full"
                  >
                    Cancel Subscription
                  </Button>
                </Tooltip>
              )}
            </div>
          </div>
        </div>

        {/* Billing Info Side Panel */}
        <div className="flex w-full flex-col gap-4 lg:w-80">
          {/* Next Payment Card */}
          {subscription?.next_billing_date && (
            <div className="rounded-2xl bg-zinc-800/40 p-5 backdrop-blur-xl">
              <div className="mb-3 flex items-center gap-2">
                <Calendar03Icon className="h-4 w-4 text-blue-400" />
                <span className="text-sm font-medium text-zinc-300">
                  Next Payment
                </span>
              </div>
              <div className="space-y-2">
                <p className="text-lg font-semibold text-white">
                  {formatDate(subscription.next_billing_date)}
                </p>
                {daysUntilNextBilling !== null && (
                  <p className="text-sm text-zinc-400">
                    {daysUntilNextBilling === 0
                      ? "Due today"
                      : daysUntilNextBilling === 1
                        ? "Due tomorrow"
                        : `In ${daysUntilNextBilling} days`}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Subscription Details Card */}
          <div className="rounded-2xl bg-zinc-800/40 p-5 backdrop-blur-xl">
            <div className="mb-3 flex items-center gap-2">
              <CreditCardIcon className="h-4 w-4 text-green-400" />
              <span className="text-sm font-medium text-zinc-300">
                Subscription Details
              </span>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-zinc-400">Subscription ID</span>
                <span
                  className="max-w-32 truncate font-mono text-zinc-300"
                  title={subscription?.dodo_subscription_id}
                >
                  {subscription?.dodo_subscription_id?.slice(-8) || "N/A"}
                </span>
              </div>
              {subscription?.previous_billing_date && (
                <div className="flex justify-between">
                  <span className="text-zinc-400">Last Payment</span>
                  <span className="text-zinc-300">
                    {formatDate(subscription.previous_billing_date)}
                  </span>
                </div>
              )}
              {subscription?.cancelled_at && (
                <div className="flex justify-between">
                  <span className="text-zinc-400">Cancelled On</span>
                  <span className="text-red-400">
                    {formatDate(subscription.cancelled_at)}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Plan Features */}
          {plan?.features && plan.features.length > 0 && (
            <div className="rounded-2xl bg-zinc-800/40 p-5 backdrop-blur-xl">
              <span className="mb-3 block text-sm font-medium text-zinc-300">
                Plan Features
              </span>
              <ul className="space-y-2">
                {plan.features.slice(0, 5).map((feature) => (
                  <li
                    key={feature}
                    className="flex items-start gap-2 text-sm text-zinc-400"
                  >
                    <span className="mt-1 text-green-400">✓</span>
                    <span>{feature}</span>
                  </li>
                ))}
                {plan.features.length > 5 && (
                  <li className="text-xs text-zinc-500">
                    +{plan.features.length - 5} more features
                  </li>
                )}
              </ul>
            </div>
          )}
        </div>
      </div>
    </SettingsCard>
  );
}
