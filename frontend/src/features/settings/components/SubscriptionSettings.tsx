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
import { SettingsCard } from "@/features/settings/components/SettingsCard";
import { CreditCardIcon } from "@/icons";

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

  // Free plan display
  if (!subscriptionStatus?.is_subscribed || !subscriptionStatus.current_plan) {
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
                    className="flex items-center gap-[2px] text-xs"
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
            <img
              src="/images/wallpapers/field.webp"
              alt="Subscription illustration"
              className="h-full w-full object-cover"
            />
          </div>
        </div>
      </SettingsCard>
    );
  }

  const plan = subscriptionStatus.current_plan;
  const subscription = subscriptionStatus.subscription;

  // Convert price to USD for display
  const priceInUSDCents = convertToUSDCents(plan.amount, plan.currency);
  const priceFormatted = formatUSDFromCents(priceInUSDCents);

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case "active":
        return "success";
      case "created":
        return "warning";
      case "cancelled":
      case "expired":
        return "danger";
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
      default:
        return status;
    }
  };

  return (
    <SettingsCard
      icon={<CreditCardIcon className="h-5 w-5 text-blue-400" />}
      title="Subscription"
    >
      <div className="relative w-full overflow-hidden rounded-2xl bg-zinc-800/40 p-6 backdrop-blur-xl">
        <div className="flex h-full flex-col gap-4">
          {/* Header */}
          <div className="flex flex-row items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-2xl font-semibold text-white">
                {plan.name}
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
              <span className="text-2xl text-zinc-400">USD</span>
            </div>
            <span className="min-h-5 text-sm font-normal text-zinc-400">
              / per {plan.duration}
            </span>
          </div>

          {/* Plan Information */}
          <div className="mt-2 flex-1 space-y-3">
            {plan.description && (
              <div className="mb-3 text-sm text-zinc-300">
                {plan.description}
              </div>
            )}

            <div className="flex items-center justify-between">
              <span className="text-sm text-zinc-400">Billing Cycle</span>
              <span className="font-medium text-white capitalize">
                {plan.duration}
              </span>
            </div>

            {subscriptionStatus.days_remaining !== undefined &&
              subscriptionStatus.days_remaining !== null && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-400">Days Remaining</span>
                  <span className="font-medium text-white">
                    {subscriptionStatus.days_remaining} days
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
    </SettingsCard>
  );
}
