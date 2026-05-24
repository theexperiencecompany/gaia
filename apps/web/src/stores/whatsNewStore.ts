import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";

interface WhatsNewState {
  // Persistence
  lastSeenReleaseId: string | null;
  lastSeenReleaseDate: string | null;
  dismissedUntilReleaseId: string | null;
  // Modal UI (not persisted)
  isModalOpen: boolean;
  modalInitialIndex: number;
  // Actions
  markAllSeen: (latestId: string, latestDate: string) => void;
  dismissCard: (latestId: string) => void;
  openModal: (initialIndex?: number) => void;
  closeModal: () => void;
}

export const useWhatsNewStore = create<WhatsNewState>()(
  devtools(
    persist(
      (set) => ({
        lastSeenReleaseId: null,
        lastSeenReleaseDate: null,
        dismissedUntilReleaseId: null,
        isModalOpen: false,
        modalInitialIndex: 0,

        markAllSeen: (latestId, latestDate) =>
          set(
            { lastSeenReleaseId: latestId, lastSeenReleaseDate: latestDate },
            false,
            "whatsNew/markAllSeen",
          ),

        dismissCard: (latestId) =>
          set(
            { dismissedUntilReleaseId: latestId },
            false,
            "whatsNew/dismissCard",
          ),

        openModal: (initialIndex = 0) =>
          set(
            { isModalOpen: true, modalInitialIndex: initialIndex },
            false,
            "whatsNew/openModal",
          ),

        closeModal: () =>
          set({ isModalOpen: false }, false, "whatsNew/closeModal"),
      }),
      {
        name: "gaia-whats-new",
        partialize: (state) => ({
          lastSeenReleaseId: state.lastSeenReleaseId,
          lastSeenReleaseDate: state.lastSeenReleaseDate,
          dismissedUntilReleaseId: state.dismissedUntilReleaseId,
        }),
      },
    ),
    { name: "whatsNew-store" },
  ),
);

export const useWhatsNewModal = () =>
  useWhatsNewStore(
    useShallow((s) => ({
      isModalOpen: s.isModalOpen,
      modalInitialIndex: s.modalInitialIndex,
      openModal: s.openModal,
      closeModal: s.closeModal,
    })),
  );
