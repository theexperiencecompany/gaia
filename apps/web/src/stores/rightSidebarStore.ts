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

export const useRightSidebar = create<RightSidebarState>((set) => ({
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
  openWithContent: (content, variant) =>
    set((state) => ({
      content,
      isOpen: true,
      variant: variant ?? state.variant,
    })),
  // Closing only flips isOpen — the CSS transition (translateX/width) animates
  // the panel out, and the offscreen content is invisible. Keeping the content
  // mounted means the next open replaces it deterministically without any
  // timer-based race against the previous close.
  close: () => set({ isOpen: false }),
}));
