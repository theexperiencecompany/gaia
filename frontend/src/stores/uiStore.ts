import { ReactNode } from "react";
import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";

import { ImageResult } from "@/types/features/convoTypes";

export interface HeaderState {
  component: ReactNode | null;
}

export type SidebarVariant =
  | "default"
  | "chat"
  | "mail"
  | "todos"
  | "calendar"
  | "notes"
  | "goals";

interface UIState {
  // Image dialog
  imageDialogOpen: boolean;
  selectedImage: ImageResult | null;

  // Header
  header: HeaderState;

  // Sidebar
  sidebarOpen: boolean;
  mobileSidebarOpen: boolean;
  sidebarVariant: SidebarVariant;

  // Integrations
  integrationsAccordionExpanded: boolean;

  // Menu
  menuAccordionExpanded: boolean;
}

interface UIActions {
  // Image dialog
  openImageDialog: (image: ImageResult) => void;
  closeImageDialog: () => void;

  // Header
  setHeader: (component: ReactNode) => void;

  // Sidebar
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleMobileSidebar: () => void;
  setMobileSidebarOpen: (open: boolean) => void;
  setSidebarVariant: (variant: SidebarVariant) => void;

  // Integrations
  setIntegrationsAccordionExpanded: (expanded: boolean) => void;

  // Menu
  setMenuAccordionExpanded: (expanded: boolean) => void;
}

type UIStore = UIState & UIActions;

const initialState: UIState = {
  imageDialogOpen: false,
  selectedImage: null,
  header: { component: null },
  sidebarOpen: true,
  mobileSidebarOpen: false,
  sidebarVariant: "default",
  integrationsAccordionExpanded: true,
  menuAccordionExpanded: true,
};

export const useUIStore = create<UIStore>()(
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

        // Header actions
        setHeader: (component) =>
          set(
            {
              header: { component },
            },
            false,
            "setHeader",
          ),

        // Sidebar actions
        toggleSidebar: () =>
          set(
            (state) => ({ sidebarOpen: !state.sidebarOpen }),
            false,
            "toggleSidebar",
          ),

        setSidebarOpen: (sidebarOpen) =>
          set({ sidebarOpen }, false, "setSidebarOpen"),

        toggleMobileSidebar: () =>
          set(
            (state) => ({ mobileSidebarOpen: !state.mobileSidebarOpen }),
            false,
            "toggleMobileSidebar",
          ),

        setMobileSidebarOpen: (mobileSidebarOpen) =>
          set({ mobileSidebarOpen }, false, "setMobileSidebarOpen"),

        setSidebarVariant: (sidebarVariant) =>
          set({ sidebarVariant }, false, "setSidebarVariant"),

        // Integrations actions
        setIntegrationsAccordionExpanded: (integrationsAccordionExpanded) =>
          set(
            { integrationsAccordionExpanded },
            false,
            "setIntegrationsAccordionExpanded",
          ),

        // Menu actions
        setMenuAccordionExpanded: (menuAccordionExpanded) =>
          set({ menuAccordionExpanded }, false, "setMenuAccordionExpanded"),
      }),
      {
        name: "ui-storage",
        partialize: (state) => ({
          sidebarOpen: state.sidebarOpen,
          sidebarVariant: state.sidebarVariant,
          integrationsAccordionExpanded: state.integrationsAccordionExpanded,
          menuAccordionExpanded: state.menuAccordionExpanded,
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

export const useUIStoreHeader = () =>
  useUIStore(
    useShallow((state) => ({
      header: state.header.component,
      setHeader: state.setHeader,
    })),
  );

export const useUIStoreSidebar = () =>
  useUIStore(
    useShallow((state) => ({
      isOpen: state.sidebarOpen,
      isMobileOpen: state.mobileSidebarOpen,
      variant: state.sidebarVariant,
      toggle: state.toggleSidebar,
      setOpen: state.setSidebarOpen,
      toggleMobile: state.toggleMobileSidebar,
      setMobileOpen: state.setMobileSidebarOpen,
      setVariant: state.setSidebarVariant,
    })),
  );

export const useIntegrationsAccordion = () =>
  useUIStore(
    useShallow((state) => ({
      isExpanded: state.integrationsAccordionExpanded,
      setExpanded: state.setIntegrationsAccordionExpanded,
    })),
  );

export const useMenuAccordion = () =>
  useUIStore(
    useShallow((state) => ({
      isExpanded: state.menuAccordionExpanded,
      setExpanded: state.setMenuAccordionExpanded,
    })),
  );
