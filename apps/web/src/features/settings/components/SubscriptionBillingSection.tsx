import type { Subscription } from "@/features/pricing/api/pricingApi";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { formatDate } from "@/features/settings/utils/subscriptionSummary";

interface SubscriptionBillingSectionProps {
  subscription?: Subscription;
  billingCycle: string;
  nextBillingLabel: string | null;
}

/** The dated facts about an active subscription, one row each. */
export function SubscriptionBillingSection({
  subscription,
  billingCycle,
  nextBillingLabel,
}: SubscriptionBillingSectionProps) {
  return (
    <SettingsSection title="Billing">
      <SettingsRow label="Billing cycle">
        <span className="text-sm capitalize text-zinc-300">{billingCycle}</span>
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
        <SettingsRow label="Subscription ID" description="For support queries">
          <span
            className="font-mono text-sm text-zinc-500"
            title={subscription.dodo_subscription_id}
          >
            ···{subscription.dodo_subscription_id.slice(-8)}
          </span>
        </SettingsRow>
      )}
    </SettingsSection>
  );
}
