"use client";

import { create } from "zustand";

interface CommandMenuStore {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

/**
 * Global open-state for the command menu. Anywhere in the app can trigger it:
 *   useCommandMenuStore.getState().open()
 * No synthetic keyboard events, no prop drilling — plug and play.
 */
export const useCommandMenuStore = create<CommandMenuStore>((set) => ({
  isOpen: false,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
  toggle: () => set((state) => ({ isOpen: !state.isOpen })),
}));
