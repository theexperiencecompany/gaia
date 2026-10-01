import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type { BrowserCardStatus } from "@/features/browser/utils";
import type { BrowserHandoffSnapshot } from "@/types/features/browserTaskTypes";

/** What the panel shows of its card, mirrored from the card's snapshots. */
interface BrowserPanelView {
  /** The session the run is on now: it changes when the run falls back to another engine. */
  sessionId: string | null;
  liveViewUrl: string | null;
  status: BrowserCardStatus | null;
  currentTask: string | null;
  pendingHandoff: BrowserHandoffSnapshot | null;
}

/**
 * Live state for the browser side panel.
 *
 * The chat's browser card is the SSE-driven source of truth: while it owns the
 * panel it mirrors the fields the panel needs into this store, and the panel
 * (mounted in the right sidebar) renders purely from here. The owner is the
 * card, by `cardId`, not a session: a run that falls back to a new session is
 * still the same card, and its panel must follow it there.
 */
interface BrowserPanelState extends BrowserPanelView {
  cardId: string | null;
  open: (cardId: string) => void;
  close: () => void;
  sync: (cardId: string, view: BrowserPanelView) => void;
}

const EMPTY_VIEW: BrowserPanelView = {
  sessionId: null,
  liveViewUrl: null,
  status: null,
  currentTask: null,
  pendingHandoff: null,
};

export const useBrowserPanel = create<BrowserPanelState>()(
  devtools(
    (set) => ({
      cardId: null,
      ...EMPTY_VIEW,
      open: (cardId) => set({ cardId }, false, "browserPanel/open"),
      close: () =>
        set({ cardId: null, ...EMPTY_VIEW }, false, "browserPanel/close"),
      sync: (cardId, view) =>
        set(
          // Only the card shown in the panel may write: a second concurrent
          // browser card must not hijack the open panel.
          (state) => (state.cardId === cardId ? view : state),
          false,
          "browserPanel/sync",
        ),
    }),
    { name: "browserPanel-store" },
  ),
);
