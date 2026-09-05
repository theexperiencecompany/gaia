"use client";

import { Button } from "@heroui/button";
import { ShineBorder } from "@/components/ui/shine-border";
import { paywallCopyFor } from "@/features/pricing/constants";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { cn } from "@/lib/utils";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

/**
 * Quiet notice shown directly above the composer for a non-subscribed user.
 * Renders in neither the unknown state (avoids a flash for paying users on a
 * cold subscription-status cache) nor for a paid user. Lives outside
 * `Composer` (mounted by `NewChatSection` and `ChatPage` next to it) so the
 * composer box, and the integrations pill tucked behind it, stay exactly as
 * they are for paying users.
 */
interface PaywallNoticeProps {
  /** Spacing hook for the mount site (e.g. clearance above the composer). */
  className?: string;
}

export function PaywallNotice({ className }: PaywallNoticeProps = {}) {
  const { isPaid, isUnknown, hasEverSubscribed } = useIsPaid();
  const openPaywallModal = usePaywallModalStore((s) => s.openModal);

  if (isUnknown || isPaid) return null;

  const copy = paywallCopyFor(hasEverSubscribed);

  return (
    // `searchbar` carries the composer's own width rule (50% desktop / 95%
    // phone) so this notice lines up with the box. The shine border is the
    // same one the Pro pricing card wears, so the notice reads as "Pro".
    <div className={cn("flex w-full justify-center", className)}>
      <div className="searchbar relative flex items-center justify-between gap-3 overflow-hidden rounded-2xl bg-zinc-800 px-4 py-2.5">
        <ShineBorder borderWidth={1} shineColor={["#00bbff", "#A7F3FF"]} />
        <p className="text-xs text-zinc-400">{copy.composer}</p>
        <Button
          size="sm"
          color="primary"
          className="shrink-0 font-medium text-black"
          onPress={() => openPaywallModal()}
        >
          {copy.cta}
        </Button>
      </div>
    </div>
  );
}
