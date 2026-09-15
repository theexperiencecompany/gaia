import type { ReactNode } from "react";
import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";

import type { RightSidebarMode, RightSidebarState } from "./layoutStore.types";

export interface HeaderState {
  component: ReactNode | null;
}

interface LayoutState {
  // Left sidebar
  sidebarOpen: boolean;
  mobileSidebarOpen: boolean;

  // Header (rendered by HeaderManager inside the main layout shell)
  header: HeaderState;

  // Right sidebar. Only the presentation mode and open flag live here — the
  // panel itself is portalled into the slot by the page that owns its data,
  // so no React element is ever stored.
  rightSidebar: RightSidebarState;
}

interface LayoutActions {
  setSidebarOpen: (open: boolean) => void;
  setMobileSidebarOpen: (open: boolean) => void;
  setHeader: (component: ReactNode) => void;
  openRightSidebar: (mode: RightSidebarMode) => void;
  closeRightSidebar: () => void;
}

export type LayoutStore = LayoutState & LayoutActions;

const initialState: LayoutState = {
  sidebarOpen: true,
  mobileSidebarOpen: false,
  header: { component: null },
  rightSidebar: { isOpen: false, mode: "sidebar" },
};

export const useLayoutStore = create<LayoutStore>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,

        setSidebarOpen: (sidebarOpen) =>
          set({ sidebarOpen }, false, "setSidebarOpen"),

        setMobileSidebarOpen: (mobileSidebarOpen) =>
          set({ mobileSidebarOpen }, false, "setMobileSidebarOpen"),

        setHeader: (component) =>
          set({ header: { component } }, false, "setHeader"),

        openRightSidebar: (mode) =>
          set(
            { rightSidebar: { isOpen: true, mode } },
            false,
            "openRightSidebar",
          ),

        // Closing only flips isOpen — the CSS transition (translateX/width)
        // animates the panel out, and keeping the mode means the outgoing panel
        // animates out in the same chrome it opened in.
        closeRightSidebar: () =>
          set(
            (state) => ({
              rightSidebar: { ...state.rightSidebar, isOpen: false },
            }),
            false,
            "closeRightSidebar",
          ),
      }),
      {
        name: "layout-storage",
        partialize: (state) => ({ sidebarOpen: state.sidebarOpen }),
      },
    ),
    { name: "layout-store" },
  ),
);

export const useLayoutSidebar = () =>
  useLayoutStore(
    useShallow((state) => ({
      isOpen: state.sidebarOpen,
      isMobileOpen: state.mobileSidebarOpen,
      setOpen: state.setSidebarOpen,
      setMobileOpen: state.setMobileSidebarOpen,
    })),
  );

export const useLayoutHeader = () =>
  useLayoutStore(
    useShallow((state) => ({
      header: state.header.component,
      setHeader: state.setHeader,
    })),
  );

export const useRightSidebarState = () =>
  useLayoutStore(
    useShallow((state) => ({
      isOpen: state.rightSidebar.isOpen,
      mode: state.rightSidebar.mode,
    })),
  );

export const useOpenRightSidebar = () =>
  useLayoutStore((state) => state.openRightSidebar);

export const useCloseRightSidebar = () =>
  useLayoutStore((state) => state.closeRightSidebar);
