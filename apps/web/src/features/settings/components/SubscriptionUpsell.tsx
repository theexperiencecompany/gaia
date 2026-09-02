"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { paywallCopyFor } from "@/features/pricing/constants";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

interface SubscriptionUpsellProps {
  /** Separates the lapsed audience from the paid-only migration audience. */
  hasEverSubscribed?: boolean;
}

/** The settings plan page for someone without an active subscription. */
export function SubscriptionUpsell({
  hasEverSubscribed,
}: SubscriptionUpsellProps) {
  const openPaywallModal = usePaywallModalStore((s) => s.openModal);
  const copy = paywallCopyFor(hasEverSubscribed);

  return (
    <SettingsPage>
      {/* Plan summary header */}
      <div className="rounded-2xl bg-zinc-900/60 px-5 py-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-medium text-zinc-500">Current Plan</p>
            <p className="mt-1 text-2xl font-semibold text-white">
              {copy.planLabel}
            </p>
          </div>
          <Chip color="warning" variant="flat" size="sm" className="text-xs">
            Inactive
          </Chip>
        </div>
        <p className="mt-1 text-sm text-zinc-500">{copy.body}</p>
      </div>

      <SettingsSection title={`${copy.cta} to GAIA Pro`}>
        <div className="px-4 py-4 space-y-3">
          <p className="text-sm text-zinc-400">
            A subscription covers the server costs and unlocks chat, workflows,
            priority support, and private Discord channels.
          </p>
          <Button
            color="primary"
            className="w-full font-semibold text-black"
            size="sm"
            onPress={() => openPaywallModal(undefined, { dismissible: true })}
          >
            View plans
          </Button>
        </div>
      </SettingsSection>
    </SettingsPage>
  );
}
