import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type {
  BrowserHandoffSnapshot,
  BrowserSessionStatus,
} from "@/types/features/browserTaskTypes";

/**
 * Live state for the browser side panel.
 *
 * The chat's browser card is the SSE-driven source of truth: while its task is
 * active it mirrors the fields the panel needs into this store, and the panel
 * (mounted in the right sidebar) renders purely from here. `sessionId` doubles
 * as the "panel is showing this session" flag the card uses to hand the single
 * live-view socket over to the panel instead of streaming twice.
 */
interface BrowserPanelState {
  sessionId: string | null;
  socketUrl: string | null;
  pageUrl: string | null;
  status: BrowserSessionStatus | null;
  currentTask: string | null;
  pendingHandoff: BrowserHandoffSnapshot | null;
  open: (sessionId: string) => void;
  close: () => void;
  sync: (update: {
    sessionId: string;
    socketUrl: string | null;
    pageUrl: string | null;
    status: BrowserSessionStatus;
    currentTask: string | null;
    pendingHandoff: BrowserHandoffSnapshot | null;
  }) => void;
}

export const useBrowserPanel = create<BrowserPanelState>()(
  devtools(
    (set) => ({
      sessionId: null,
      socketUrl: null,
      pageUrl: null,
      status: null,
      currentTask: null,
      pendingHandoff: null,
      open: (sessionId) => set({ sessionId }, false, "browserPanel/open"),
      close: () =>
        set(
          {
            sessionId: null,
            socketUrl: null,
            pageUrl: null,
            status: null,
            currentTask: null,
            pendingHandoff: null,
          },
          false,
          "browserPanel/close",
        ),
      sync: (update) =>
        set(
          (state) => {
            // Only the session shown in the panel may write — a second
            // concurrent browser card must not hijack the open panel.
            if (state.sessionId !== update.sessionId) return state;
            return { ...update };
          },
          false,
          "browserPanel/sync",
        ),
    }),
    { name: "browserPanel-store" },
  ),
);
