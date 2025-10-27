import { create } from "zustand";

/**
 * Right sidebar variants:
 * - "sheet": Modal overlay that appears on top of content (doesn't shift layout)
 * - "sidebar": Persistent sidebar that pushes/shifts the main content layout
 */
export type RightSidebarVariant = "sheet" | "sidebar";

interface RightSidebarState {
  content: React.ReactNode | null;
  isOpen: boolean;
  variant: RightSidebarVariant;
  setContent: (content: React.ReactNode | null) => void;
  setVariant: (variant: RightSidebarVariant) => void;
  open: (variant?: RightSidebarVariant) => void;
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
  close: () => set({ isOpen: false, content: null }),
}));
