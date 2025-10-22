import { create } from "zustand";

interface RightSidebarState {
  content: React.ReactNode | null;
  isOpen: boolean;
  setContent: (content: React.ReactNode | null) => void;
  open: () => void;
  close: () => void;
}

export const useRightSidebar = create<RightSidebarState>((set) => ({
  content: null,
  isOpen: false,
  setContent: (content) => set({ content, isOpen: !!content }),
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false, content: null }),
}));
