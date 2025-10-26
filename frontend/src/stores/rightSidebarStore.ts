import { create } from "zustand";

export type RightSidebarVariant = "overlay" | "push";

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
  variant: "overlay",
  setContent: (content) => set({ content }),
  setVariant: (variant) => set({ variant }),
  open: (variant) =>
    set((state) => ({
      isOpen: true,
      variant: variant ?? state.variant,
    })),
  close: () => set({ isOpen: false, content: null }),
}));
