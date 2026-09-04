"use client";

import { Button } from "@heroui/button";
import { paywallCopyFor } from "@/features/pricing/constants";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

/**
 * Quiet notice shown directly above the composer for a non-subscribed user.
 * Renders in neither the unknown state (avoids a flash for paying users on a
 * cold subscription-status cache) nor for a paid user. Lives outside
 * `Composer` (mounted by `NewChatSection` and `ChatPage` next to it) so the
 * composer box, and the integrations pill tucked behind it, stay exactly as
 * they are for paying users.
 */
export function PaywallNotice() {
  const { isPaid, isUnknown, hasEverSubscribed } = useIsPaid();
  const openPaywallModal = usePaywallModalStore((s) => s.openModal);

  if (isUnknown || isPaid) return null;

  const copy = paywallCopyFor(hasEverSubscribed);

  return (
    // `searchbar` carries the composer's own width rule (50% desktop / 95%
    // phone) so this notice lines up with the box below it. The bottom margin
    // clears the integrations pill, which peeks 2.25rem above the composer.
    <div className="flex w-full justify-center">
      <div className="searchbar mb-10 flex items-center justify-between gap-3 rounded-2xl bg-zinc-800 px-4 py-2.5">
        <p className="text-xs text-zinc-400">{copy.composer}</p>
        <Button
          size="sm"
          color="primary"
          radius="full"
          className="shrink-0 font-medium text-black"
          onPress={() => openPaywallModal()}
        >
          {copy.cta}
        </Button>
      </div>
    </div>
  );
}
