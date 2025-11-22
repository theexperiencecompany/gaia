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
        <div className="space-y-4">
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-sm text-zinc-400">Plan</span>
              <span className="font-medium text-white">Free</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-zinc-400">Price</span>
              <span className="font-medium text-white">$0</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-zinc-400">Status</span>
              <span className="font-medium text-white">Active</span>
            </div>
          </div>

          <div className="border-t border-zinc-700 pt-4">
            <Button color="primary" className="w-full" onPress={handleUpgrade}>
              Upgrade to Pro
            </Button>
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
      <div className="mb-4 flex justify-end">
        <Chip
          color={getStatusColor(subscription?.status || "unknown")}
          variant="flat"
          size="sm"
        >
          {getStatusText(subscription?.status || "unknown")}
        </Chip>
      </div>

      <div className="space-y-4">
        {/* Plan Details */}
        <div className="space-y-3">
          <div className="flex justify-between">
            <span className="text-sm text-zinc-400">Plan</span>
            <span className="font-medium text-white">{plan.name}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-zinc-400">Price</span>
            <span className="font-medium text-white">
              {priceFormatted} / {plan.duration}
            </span>
          </div>
          {subscriptionStatus.days_remaining !== undefined && (
            <div className="flex justify-between">
              <span className="text-sm text-zinc-400">Days remaining</span>
              <span className="font-medium text-white">
                {subscriptionStatus.days_remaining}
              </span>
            </div>
          )}
        </div>

        <div className="border-t border-zinc-700 pt-4">
          {/* Actions */}
          <div className="flex flex-col gap-2">
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
