import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface LoginModalStore {
  open: boolean;
  /**
   * When true, openModal() is a no-op. Surfaces with their own sign-in
   * affordance (the desktop assistant popup) suppress the modal — a
   * full-screen login dialog makes no sense in a compact pill window.
   */
  suppressed: boolean;
  setOpen: (open: boolean) => void;
  openModal: () => void;
  closeModal: () => void;
  suppressModal: () => void;
}

export const useLoginModalStore = create<LoginModalStore>()(
  devtools(
    (set, get) => ({
      open: false,
      suppressed: false,
      setOpen: (open) => set({ open }, false, "setOpen"),
      openModal: () => {
        if (get().suppressed) return;
        set({ open: true }, false, "openModal");
      },
      closeModal: () => set({ open: false }, false, "closeModal"),
      suppressModal: () =>
        set({ suppressed: true, open: false }, false, "suppressModal"),
    }),
    { name: "loginModal-store" },
  ),
);
