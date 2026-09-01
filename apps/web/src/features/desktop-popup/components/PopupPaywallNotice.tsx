"use client";

import { Button } from "@heroui/button";
import { useElectron } from "@/hooks/useElectron";
import { usePaywallModalStore } from "@/stores/paywallModalStore";

const PRICING_PATH = "/pricing";

/**
 * The paid-only wall, as it appears in the desktop popup.
 *
 * The popup cannot use `GlobalPaywallModal`: its composer window is a 420x48
 * frameless capsule, and a HeroUI `Modal` portals a full-viewport blurred
 * backdrop that would be clipped to that sliver. So the block renders inline
 * in the feed window instead — the popup's only content-sized surface, which
 * the main process grows to fit whatever this reports.
 *
 * State arrives over the popup's BroadcastChannel (`sync.ts`): the 402 lands
 * in the composer window, which owns sending, and is mirrored here.
 */
export default function PopupPaywallNotice() {
  const open = usePaywallModalStore((s) => s.open);
  const offer = usePaywallModalStore((s) => s.offer);
  const { openExternal } = useElectron();

  if (!open) return null;

  // The backend mints a personal checkout link into the 402 body. When Dodo is
  // unreachable it deliberately sends none — the block still stands, so fall
  // back to the pricing page rather than leaving the user with no way out.
  const target =
    offer?.checkoutUrl ?? `${window.location.origin}${PRICING_PATH}`;

  return (
    <div className="flex flex-col gap-3 rounded-2xl bg-zinc-800 p-4">
      <div className="flex flex-col gap-1">
        <p className="font-medium text-sm text-zinc-100">GAIA is Pro-only</p>
        <p className="text-xs text-zinc-400">
          {offer?.message ??
            "Subscribe to GAIA Pro to keep chatting from the popup."}
        </p>
      </div>

      {offer?.discountCode && (
        <p className="text-success text-xs">
          Use code <span className="font-semibold">{offer.discountCode}</span>{" "}
          at checkout.
        </p>
      )}

      <Button
        size="sm"
        color="primary"
        radius="full"
        className="font-medium text-black"
        onPress={() => openExternal(target)}
      >
        Subscribe in your browser
      </Button>
    </div>
  );
}
