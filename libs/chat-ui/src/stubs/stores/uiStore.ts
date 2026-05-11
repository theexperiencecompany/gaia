/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { ReactNode } from "react";

import type { ImageResult } from "@/types/features/convoTypes";

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
  imageDialogOpen: boolean;
  selectedImage: ImageResult | null;
  header: HeaderState;
  sidebarOpen: boolean;
  mobileSidebarOpen: boolean;
  sidebarVariant: SidebarVariant;
  integrationsAccordionExpanded: boolean;
  menuAccordionExpanded: boolean;
}

interface UIActions {
  openImageDialog: (image: ImageResult) => void;
  closeImageDialog: () => void;
  setHeader: (component: ReactNode) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleMobileSidebar: () => void;
  setMobileSidebarOpen: (open: boolean) => void;
  setSidebarVariant: (variant: SidebarVariant) => void;
  setIntegrationsAccordionExpanded: (expanded: boolean) => void;
  setMenuAccordionExpanded: (expanded: boolean) => void;
}

type UIStore = UIState & UIActions;

const noop = () => {};

const frozenState: UIStore = Object.freeze({
  imageDialogOpen: false,
  selectedImage: null,
  header: { component: null },
  sidebarOpen: true,
  mobileSidebarOpen: false,
  sidebarVariant: "default" as SidebarVariant,
  integrationsAccordionExpanded: true,
  menuAccordionExpanded: true,
  openImageDialog: noop,
  closeImageDialog: noop,
  setHeader: noop,
  toggleSidebar: noop,
  setSidebarOpen: noop,
  toggleMobileSidebar: noop,
  setMobileSidebarOpen: noop,
  setSidebarVariant: noop,
  setIntegrationsAccordionExpanded: noop,
  setMenuAccordionExpanded: noop,
});

export const useImageDialog = () => ({
  isOpen: false,
  selectedImage: null as ImageResult | null,
  openDialog: noop as UIActions["openImageDialog"],
  closeDialog: noop as UIActions["closeImageDialog"],
});

export const useUIStoreHeader = () => ({
  header: null as ReactNode | null,
  setHeader: noop as UIActions["setHeader"],
});

export const useUIStoreSidebar = () => ({
  isOpen: true,
  isMobileOpen: false,
  variant: "default" as SidebarVariant,
  toggle: noop as UIActions["toggleSidebar"],
  setOpen: noop as UIActions["setSidebarOpen"],
  toggleMobile: noop as UIActions["toggleMobileSidebar"],
  setMobileOpen: noop as UIActions["setMobileSidebarOpen"],
  setVariant: noop as UIActions["setSidebarVariant"],
});

export const useIntegrationsAccordion = () => ({
  isExpanded: true,
  setExpanded: noop as UIActions["setIntegrationsAccordionExpanded"],
});

// In case any consumer reaches for the raw store
type Selector<U> = (state: UIStore) => U;
interface UseStoreFn {
  <U>(selector: Selector<U>): U;
  (): UIStore;
  getState: () => UIStore;
}
const useUIStore: UseStoreFn = (<U,>(selector?: Selector<U>) => {
  if (selector) return selector(frozenState);
  return frozenState;
}) as UseStoreFn;
useUIStore.getState = () => frozenState;
export default useUIStore;
