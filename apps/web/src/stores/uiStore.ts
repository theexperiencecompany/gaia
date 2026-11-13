import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";

import type { ImageResult } from "@/types/features/convoTypes";

interface UIState {
  // Image dialog
  imageDialogOpen: boolean;
  selectedImage: ImageResult | null;

  // Integrations
  integrationsAccordionExpanded: boolean;
  integrationModalOpen: boolean;
}

interface UIActions {
  // Image dialog
  openImageDialog: (image: ImageResult) => void;
  closeImageDialog: () => void;

  // Integrations
  setIntegrationsAccordionExpanded: (expanded: boolean) => void;
  openIntegrationModal: () => void;
  closeIntegrationModal: () => void;
}

type UIStore = UIState & UIActions;

const initialState: UIState = {
  imageDialogOpen: false,
  selectedImage: null,
  integrationsAccordionExpanded: true,
  integrationModalOpen: false,
};

const useUIStore = create<UIStore>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,

        // Image dialog actions
        openImageDialog: (image) =>
          set(
            {
              imageDialogOpen: true,
              selectedImage: image,
            },
            false,
            "openImageDialog",
          ),

        closeImageDialog: () =>
          set(
            {
              imageDialogOpen: false,
              selectedImage: null,
            },
            false,
            "closeImageDialog",
          ),

        // Integrations actions
        setIntegrationsAccordionExpanded: (integrationsAccordionExpanded) =>
          set(
            { integrationsAccordionExpanded },
            false,
            "setIntegrationsAccordionExpanded",
          ),

        openIntegrationModal: () =>
          set({ integrationModalOpen: true }, false, "openIntegrationModal"),

        closeIntegrationModal: () =>
          set({ integrationModalOpen: false }, false, "closeIntegrationModal"),
      }),
      {
        name: "ui-storage",
        partialize: (state) => ({
          integrationsAccordionExpanded: state.integrationsAccordionExpanded,
        }),
      },
    ),
    { name: "ui-store" },
  ),
);

// Selectors with proper shallow comparison for Zustand v5
export const useImageDialog = () =>
  useUIStore(
    useShallow((state) => ({
      isOpen: state.imageDialogOpen,
      selectedImage: state.selectedImage,
      openDialog: state.openImageDialog,
      closeDialog: state.closeImageDialog,
    })),
  );

export const useIntegrationsAccordion = () =>
  useUIStore(
    useShallow((state) => ({
      isExpanded: state.integrationsAccordionExpanded,
      setExpanded: state.setIntegrationsAccordionExpanded,
    })),
  );

export const useIntegrationModalOpen = () =>
  useUIStore((state) => state.integrationModalOpen);

export const useIntegrationModalActions = () =>
  useUIStore(
    useShallow((state) => ({
      openIntegrationModal: state.openIntegrationModal,
      closeIntegrationModal: state.closeIntegrationModal,
    })),
  );
