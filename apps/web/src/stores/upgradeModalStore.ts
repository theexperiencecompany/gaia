import { create } from "zustand";
import { devtools } from "zustand/middleware";

import type { PaywallSource } from "@/lib/analytics";

import type {
  UpgradeModalCloseOptions,
  UpgradeModalOptions,
  UpgradeOffer,
} from "./upgradeModal.types";

interface UpgradeModalStore {
  open: boolean;
  offer: UpgradeOffer | null;
  dismissible: boolean;
  /** The surface that raised the wall now standing, for the impression. */
  source: PaywallSource | null;
  openModal: (
    offer: UpgradeOffer | undefined,
    options: UpgradeModalOptions,
  ) => void;
  closeModal: (options?: UpgradeModalCloseOptions) => void;
}

/**
 * The single Pro upsell modal's state — enforcement wall and voluntary
 * pricing view are the same store, the same offer, and the same modal; only
 * `dismissible` differs. It has two modes, chosen per call site via
 * `openModal`'s `options.dismissible`:
 *
 * - **Enforcement (default, `dismissible: false`)** — a user tried to do
 *   something that requires Pro (send a chat message, toggle a workflow, a
 *   402 `subscription_required` response) and got redirected here instead.
 *   No backdrop click, no Escape, no close button — subscribe or log out are
 *   the only exits. This is the default so every existing enforcement call
 *   site keeps today's behavior without passing anything.
 * - **Voluntary (`dismissible: true`)** — the user chose to open this
 *   themselves (an "Upgrade to Pro" button, the founder's letter discount)
 *   while already able to use the app. Trapping them here would be a UX trap,
 *   not enforcement, so the modal behaves like a normal dismissible dialog
 *   and shows the full plan picker.
 *
 * `closeModal` refuses to close an enforcement-mode modal: that guard is what
 * makes the wall a wall, wherever the close is requested from. Programmatic
 * resets that must win regardless (checkout succeeded and `useIsPaid` flipped
 * true, the desktop popup mirroring the composer window) pass `{ force: true }`.
 *
 * `openModal` raises the wall once and then leaves it standing. A single
 * blocked screen produces a 402 per gated request, and acting on every one of
 * them would rewrite the offer underneath a modal the user is already reading
 * — and silently strip the close control off one they opened voluntarily,
 * turning a plan browse into a trap. The first open owns the modal until it
 * closes.
 */
export const useUpgradeModalStore = create<UpgradeModalStore>()(
  devtools(
    (set) => ({
      open: false,
      offer: null,
      dismissible: false,
      source: null,
      openModal: (offer, options) =>
        set(
          (state) =>
            state.open
              ? state
              : {
                  open: true,
                  offer: offer ?? null,
                  dismissible: options.dismissible ?? false,
                  source: options.source,
                },
          false,
          "openModal",
        ),
      closeModal: (options) =>
        set(
          (state) =>
            state.dismissible || options?.force
              ? { open: false, offer: null, dismissible: false, source: null }
              : state,
          false,
          "closeModal",
        ),
    }),
    { name: "upgradeModal-store" },
  ),
);
