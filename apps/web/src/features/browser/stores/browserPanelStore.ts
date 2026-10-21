import { create } from "zustand";
import { devtools } from "zustand/middleware";

/**
 * Which browser card owns the side panel.
 *
 * The card renders the panel itself from its own SSE-driven state; this store
 * only decides which card that is, so a second concurrent browser card cannot
 * take over an open panel. The owner is the card, by `cardId`, not a session:
 * a run that falls back to a new session is still the same card.
 */
interface BrowserPanelState {
  cardId: string | null;
  open: (cardId: string) => void;
  close: () => void;
}

export const useBrowserPanel = create<BrowserPanelState>()(
  devtools(
    (set) => ({
      cardId: null,
      open: (cardId) => set({ cardId }, false, "browserPanel/open"),
      close: () => set({ cardId: null }, false, "browserPanel/close"),
    }),
    { name: "browserPanel-store" },
  ),
);
