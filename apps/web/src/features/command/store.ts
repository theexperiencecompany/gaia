"use client";

import { create } from "zustand";

interface CommandMenuStore {
  isOpen: boolean;
  /** Element focused when the menu opened; focus returns to it on close. */
  openedFrom: HTMLElement | null;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

// Captured synchronously in the open action — before the menu mounts and its
// input auto-focuses — so closing can restore focus to the actual opener.
const captureOpener = (): HTMLElement | null =>
  document.activeElement instanceof HTMLElement ? document.activeElement : null;

/**
 * Global open-state for the command menu. Anywhere in the app can trigger it:
 *   useCommandMenuStore.getState().open()
 * No synthetic keyboard events, no prop drilling — plug and play.
 */
export const useCommandMenuStore = create<CommandMenuStore>((set) => ({
  isOpen: false,
  openedFrom: null,
  open: () => set({ isOpen: true, openedFrom: captureOpener() }),
  close: () => set({ isOpen: false }),
  toggle: () =>
    set((state) =>
      state.isOpen
        ? { isOpen: false }
        : { isOpen: true, openedFrom: captureOpener() },
    ),
}));
