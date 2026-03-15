import { create } from "zustand";

/**
 * Right sidebar variants:
 * - "sheet": Modal overlay that appears on top of content (doesn't shift layout)
 * - "sidebar": Persistent sidebar that pushes/shifts the main content layout
 * - "artifact": Wide split-view panel optimized for file previewing
 */
export type RightSidebarVariant = "sheet" | "sidebar" | "artifact";

interface RightSidebarState {
  content: React.ReactNode | null;
  isOpen: boolean;
  variant: RightSidebarVariant;
  setContent: (content: React.ReactNode | null) => void;
  setVariant: (variant: RightSidebarVariant) => void;
  open: (variant?: RightSidebarVariant) => void;
  openWithContent: (
    content: React.ReactNode,
    variant?: RightSidebarVariant,
  ) => void;
  close: () => void;
}

// Timer/frame IDs for cancelling stale async operations on open/close races.
let closeContentTimer: ReturnType<typeof setTimeout> | null = null;
let openRafId: number | null = null;

export const useRightSidebar = create<RightSidebarState>((set, get) => ({
  content: null,
  isOpen: false,
  variant: "sidebar",
  setContent: (content) => set({ content }),
  setVariant: (variant) => set({ variant }),
  open: (variant) =>
    set((state) => ({
      isOpen: true,
      variant: variant ?? state.variant,
    })),
  openWithContent: (content, variant) => {
    // Cancel any pending content-clear from a previous close() so it doesn't
    // wipe the content we're about to set.
    if (closeContentTimer !== null) {
      clearTimeout(closeContentTimer);
      closeContentTimer = null;
    }
    if (openRafId !== null) {
      cancelAnimationFrame(openRafId);
    }

    const currentVariant = variant ?? get().variant;
    set({ content, variant: currentVariant });
    // Defer isOpen so the browser paints one frame with the sidebar off-screen
    // (translateX(100%)) before the CSS transition animates it in.
    openRafId = requestAnimationFrame(() => {
      openRafId = null;
      set({ isOpen: true });
    });
  },
  close: () => {
    // Cancel any pending open rAF so a stale open doesn't fire after close.
    if (openRafId !== null) {
      cancelAnimationFrame(openRafId);
      openRafId = null;
    }
    if (closeContentTimer !== null) {
      clearTimeout(closeContentTimer);
    }

    set({ isOpen: false });
    // Delay content clear by 300ms to allow the slide-out CSS transition to complete.
    closeContentTimer = setTimeout(() => {
      closeContentTimer = null;
      set({ content: null });
    }, 300);
  },
}));
