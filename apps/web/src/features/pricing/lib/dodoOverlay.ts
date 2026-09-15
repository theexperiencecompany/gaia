import type { CheckoutEvent } from "dodopayments-checkout";

import { DODO_CHECKOUT_MODE } from "../constants";

/** The overlay dressed as GAIA: zinc surfaces, the brand blue on the one
 *  button that matters, and a button label that matches ours. Dark only —
 *  the app is dark, so the overlay never flashes light over it. */
const CHECKOUT_OPTIONS = {
  payButtonText: "Subscribe",
  showSecurityBadge: true,
  showTimer: false,
  themeConfig: {
    radius: "16px",
    dark: {
      bgPrimary: "#18181b",
      bgSecondary: "#27272a",
      borderPrimary: "#3f3f46",
      borderSecondary: "#27272a",
      textPrimary: "#fafafa",
      textSecondary: "#a1a1aa",
      textPlaceholder: "#71717a",
      textError: "#f87171",
      textSuccess: "#4ade80",
      buttonPrimary: "#00bbff",
      buttonPrimaryHover: "#33c9ff",
      buttonTextPrimary: "#000000",
      buttonSecondary: "#27272a",
      buttonSecondaryHover: "#3f3f46",
      buttonTextSecondary: "#fafafa",
      inputFocusBorder: "#00bbff",
    },
  },
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
      theme: "dark",
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
