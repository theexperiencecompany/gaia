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
 * The popup's way out of the paid-only wall.
 *
 * Checkout cannot happen in the popup itself — it is a frameless capsule with
 * no room for a payment sheet — so the session is minted here and opened in
 * the user's browser, where the overlay and its confirmation loop live.
 *
 * Minted on the click, never on the wall going up: a session per 402 is a
 * session per gated request, nearly all of them abandoned. If minting fails
 * the pricing page is still a way to subscribe — the failure itself already
 * surfaced as a toast from the API layer, so this is a fallback, not a
 * silence.
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
      openExternal(session.payment_link);
    } catch {
      openExternal(`${window.location.origin}${PRICING_PATH}`);
    } finally {
      setIsOpeningCheckout(false);
    }
  };

  return { openCheckout, isOpeningCheckout };
}
