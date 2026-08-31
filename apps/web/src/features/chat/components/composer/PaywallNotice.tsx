"use client";

import { Button } from "@heroui/button";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

/**
 * Quiet notice shown directly above the composer for a non-subscribed user.
 * Renders in neither the unknown state (avoids a flash for paying users on a
 * cold subscription-status cache) nor for a paid user. Mounted once in
 * `Composer`, which is the single render path shared by `NewChatLayout` and
 * `ChatWithMessages`, so it covers both the empty and active-conversation
 * states.
 */
export function PaywallNotice() {
  const { isPaid, isUnknown } = useIsPaid();
  const openPaywallModal = usePaywallModalStore((s) => s.openModal);

  if (isUnknown || isPaid) return null;

  return (
    <div className="mb-2 flex w-full items-center justify-between gap-3 rounded-2xl bg-zinc-800 px-4 py-2.5">
      <p className="text-xs text-zinc-400">
        GAIA is paid-only right now — subscriptions cover the server costs.
      </p>
      <Button
        size="sm"
        color="primary"
        radius="full"
        className="shrink-0 font-medium text-black"
        onPress={() => openPaywallModal()}
      >
        Upgrade to Pro
      </Button>
    </div>
  );
}
