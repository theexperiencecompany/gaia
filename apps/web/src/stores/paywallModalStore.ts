import { create } from "zustand";
import { devtools } from "zustand/middleware";

/**
 * Payload carried into the paywall — from a 402 `subscription_required`
 * response, or any other call site that wants to gate an action behind Pro.
 * checkoutUrl/discountCode ride along from the backend so the modal doesn't
 * have to re-derive them; both are optional because non-402 call sites (the
 * composer pre-check, workflow toggle) open the modal with no offer at all.
 */
export interface PaywallOffer {
  checkoutUrl: string | null;
  discountCode: string | null;
  message?: string;
}

export interface PaywallModalOptions {
  /** See `openModal` doc-comment for when to set this. Defaults to false. */
  dismissible?: boolean;
}

interface PaywallModalStore {
  open: boolean;
  offer: PaywallOffer | null;
  dismissible: boolean;
  openModal: (offer?: PaywallOffer, options?: PaywallModalOptions) => void;
  closeModal: () => void;
}

/**
 * The paid-only paywall. It has two modes, chosen per call site via
 * `openModal`'s `options.dismissible`:
 *
 * - **Enforcement (default, `dismissible: false`)** — a user tried to do
 *   something that requires Pro (send a chat message, toggle a workflow, a
 *   402 `subscription_required` response) and got redirected here instead.
 *   No backdrop click, no Escape, no close button — subscribe or log out are
 *   the only exits. This is the default so every existing enforcement call
 *   site keeps today's behavior without passing anything.
 * - **Voluntary (`dismissible: true`)** — the user chose to open this
 *   themselves (e.g. an "Upgrade to Pro" button) while already able to use
 *   the app. Trapping them here would be a UX trap, not enforcement, so the
 *   modal behaves like a normal dismissible dialog: backdrop click, Escape,
 *   and a close button all work.
 *
 * `closeModal` exists for both the programmatic reset (e.g. once checkout
 * succeeds and `useIsPaid` flips true) and the dismissible mode's user-facing
 * close controls — its own semantics don't change between modes.
 */
export const usePaywallModalStore = create<PaywallModalStore>()(
  devtools(
    (set) => ({
      open: false,
      offer: null,
      dismissible: false,
      openModal: (offer, options) =>
        set(
          {
            open: true,
            offer: offer ?? null,
            dismissible: options?.dismissible ?? false,
          },
          false,
          "openModal",
        ),
      closeModal: () =>
        set(
          { open: false, offer: null, dismissible: false },
          false,
          "closeModal",
        ),
    }),
    { name: "paywallModal-store" },
  ),
);
