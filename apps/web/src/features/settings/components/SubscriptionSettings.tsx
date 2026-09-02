"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import { Tick02Icon } from "@icons";
import {
  useIsSubscriptionStatusUnknown,
  useUserSubscriptionStatus,
} from "@/features/pricing/hooks/usePricing";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import {
  formatDate,
  getSubscriptionSummary,
} from "@/features/settings/utils/subscriptionSummary";
import { usePricingModalStore } from "@/stores/pricingModalStore";
import { CancelSubscriptionAction } from "./CancelSubscriptionAction";
import { SubscriptionBillingSection } from "./SubscriptionBillingSection";
import { SubscriptionUpsell } from "./SubscriptionUpsell";

export function SubscriptionSettings() {
  const { data: status, refetch: refetchStatus } = useUserSubscriptionStatus();
  // True while the plan is not yet definitively known — a cold cache right
  // after a hard refresh, or the user store still rehydrating. Gates the
  // skeleton below instead of TanStack's own `isLoading`, which reports
  // false for a disabled-and-never-fetched query and would otherwise flash
  // "No subscription" at a paying user. See useIsPaid for the invariant.
  const isUnknown = useIsSubscriptionStatusUnknown();
  // Managing an existing Pro plan (monthly <-> yearly) is a different job
  // than subscribing for the first time — see the branches below.
  const openPricingModal = usePricingModalStore((s) => s.openModal);

  if (isUnknown) {
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
      <SubscriptionUpsell hasEverSubscribed={status?.has_ever_subscribed} />
    );
  }

  const plan = status.current_plan;
  const subscription = status.subscription;
  const {
    planName,
    priceFormatted,
    billingCycle,
    statusColor,
    statusText,
    cancellationScheduled,
    nextBillingLabel,
  } = getSubscriptionSummary(status);

  return (
    <SettingsPage>
      {/* Plan summary header */}
      <div className="rounded-2xl bg-zinc-900/60 px-5 py-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium text-zinc-500">Current Plan</p>
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
          {cancellationScheduled ? (
            <span className="ml-3 text-xs text-amber-500">
              Cancellation scheduled · access until{" "}
              {subscription?.next_billing_date
                ? formatDate(subscription.next_billing_date)
                : "period end"}
            </span>
          ) : (
            nextBillingLabel && (
              <span className="ml-3 text-xs text-zinc-600">
                Next billing {nextBillingLabel}
              </span>
            )
          )}
        </p>
      </div>

      <SubscriptionBillingSection
        subscription={subscription}
        billingCycle={billingCycle}
        nextBillingLabel={nextBillingLabel}
      />

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
                  <Tick02Icon
                    className="mt-0.5 shrink-0 text-emerald-400"
                    width={16}
                    height={16}
                  />
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
            onPress={() => openPricingModal()}
            size="sm"
            className="w-full"
          >
            View plans
          </Button>

          {subscription && (
            <CancelSubscriptionAction
              subscription={subscription}
              refetchStatus={refetchStatus}
            />
          )}
        </div>
      </SettingsSection>
    </SettingsPage>
  );
}
