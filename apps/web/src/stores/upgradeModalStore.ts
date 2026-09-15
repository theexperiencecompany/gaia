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
 * The single Pro upsell modal — enforcement and voluntary upgrade share the same store/offer,
 * chosen via `openModal`'s `options.dismissible` (default false = enforcement: subscribe or log
 * out are the only exits; `closeModal` refuses to close it except with `{ force: true }`, e.g.
 * `useIsPaid` flipping true or the desktop popup mirroring the composer window).
 *
 * `openModal` raises the wall once and leaves it standing: a blocked screen fires a 402 per
 * gated request, and acting on every one would rewrite or silently un-dismiss an already-open modal.
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
