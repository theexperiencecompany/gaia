import type { CheckoutEvent } from "dodopayments-checkout";

import { DODO_CHECKOUT_MODE } from "../constants";

/** The overlay's own options. The theme is set on the session the API mints
 *  (the SDK's themeConfig is deprecated and ignored). `manualRedirect` keeps
 *  the app in charge of the page: Dodo reports the charge's outcome through
 *  `checkout.status` instead of navigating the whole tab to its status page
 *  and back to a return URL carrying the customer's email. */
const CHECKOUT_OPTIONS = {
  payButtonText: "Subscribe",
  manualRedirect: true,
  showSecurityBadge: true,
  showTimer: false,
} as const;

/**
 * The Dodo checkout SDK is a module-level singleton with a single `onEvent`
 * callback registered at `Initialize`. Re-initializing per checkout would stack
 * listeners, so the SDK is initialized exactly once and the callback dispatches
 * to whichever handler the current checkout registered.
 */
let initialized = false;
let currentHandler: ((event: CheckoutEvent) => void) | null = null;

/** Opens the Dodo overlay over the app. Imported lazily so the SDK (which
 *  touches `window` and `document`) never loads during SSR or on a page that
 *  never checks out. */
export async function openDodoOverlay(
  checkoutUrl: string,
  onEvent: (event: CheckoutEvent) => void,
): Promise<void> {
  const { DodoPayments } = await import("dodopayments-checkout");

  currentHandler = onEvent;
  if (!initialized) {
    DodoPayments.Initialize({
      mode: DODO_CHECKOUT_MODE,
      displayType: "overlay",
      onEvent: (event) => currentHandler?.(event),
    });
    initialized = true;
  }

  DodoPayments.Checkout.open({ checkoutUrl, options: CHECKOUT_OPTIONS });
}

/** Closes the overlay if it is open — used once payment is confirmed so the
 *  user isn't left staring at a completed checkout. */
export async function closeDodoOverlay(): Promise<void> {
  if (!initialized) return;
  const { DodoPayments } = await import("dodopayments-checkout");
  if (DodoPayments.Checkout.isOpen()) DodoPayments.Checkout.close();
}
