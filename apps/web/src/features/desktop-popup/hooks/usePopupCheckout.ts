"use client";

import { useState } from "react";

import { pricingApi } from "@/features/pricing/api/pricingApi";
import { useElectron } from "@/hooks/useElectron";

const PRICING_PATH = "/pricing";

interface PopupCheckout {
  /** Mints a session and hands it to the user's real browser. */
  openCheckout: () => Promise<void>;
  isOpeningCheckout: boolean;
}

/**
 * The popup's way out of the paid-only wall: checkout can't happen in the
 * frameless capsule itself, so a session is minted and opened in the user's
 * browser instead.
 *
 * Minted on click, not on the wall going up, to avoid a session per gated
 * request; if minting fails, the pricing page is still a fallback.
 */
export function usePopupCheckout(): PopupCheckout {
  const { openExternal } = useElectron();
  const [isOpeningCheckout, setIsOpeningCheckout] = useState(false);

  const openCheckout = async () => {
    setIsOpeningCheckout(true);
    try {
      const session = await pricingApi.createCheckoutSession({
        billing_cycle: "monthly",
        source: "paywall_modal",
      });
      openExternal(
        session.payment_link ?? `${window.location.origin}${PRICING_PATH}`,
      );
    } catch {
      openExternal(`${window.location.origin}${PRICING_PATH}`);
    } finally {
      setIsOpeningCheckout(false);
    }
  };

  return { openCheckout, isOpeningCheckout };
}
