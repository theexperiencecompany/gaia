import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useRef,
  useState,
} from "react";
import type { DrawerLayoutMethods } from "react-native-gesture-handler/ReanimatedDrawerLayout";

interface SidebarContextValue {
  drawerRef: React.RefObject<DrawerLayoutMethods | null>;
  openSidebar: () => void;
  closeSidebar: () => void;
  toggleSidebar: () => void;
  // Internal: invoked by the DrawerLayout host to keep open-state in sync
  // when the drawer opens/closes via swipe/tap-overlay (not just our buttons).
  _notifyDrawerOpened: () => void;
  _notifyDrawerClosed: () => void;
}

const SidebarContext = createContext<SidebarContextValue | null>(null);

interface SidebarProviderProps {
  children: ReactNode;
}

export function SidebarProvider({ children }: SidebarProviderProps) {
  const drawerRef = useRef<DrawerLayoutMethods>(null);
  const isOpenRef = useRef(false);
  const [, setRender] = useState(0);

  const setIsOpen = useCallback((next: boolean) => {
    if (isOpenRef.current === next) return;
    isOpenRef.current = next;
    setRender((n) => n + 1);
  }, []);

  const openSidebar = useCallback(() => {
    drawerRef.current?.openDrawer();
    setIsOpen(true);
  }, [setIsOpen]);

  const closeSidebar = useCallback(() => {
    drawerRef.current?.closeDrawer();
    setIsOpen(false);
  }, [setIsOpen]);

  const toggleSidebar = useCallback(() => {
    if (isOpenRef.current) {
      drawerRef.current?.closeDrawer();
      setIsOpen(false);
    } else {
      drawerRef.current?.openDrawer();
      setIsOpen(true);
    }
  }, [setIsOpen]);

  const _notifyDrawerOpened = useCallback(() => setIsOpen(true), [setIsOpen]);
  const _notifyDrawerClosed = useCallback(() => setIsOpen(false), [setIsOpen]);

  return (
    <SidebarContext.Provider
      value={{
        drawerRef,
        openSidebar,
        closeSidebar,
        toggleSidebar,
        _notifyDrawerOpened,
        _notifyDrawerClosed,
      }}
    >
      {children}
    </SidebarContext.Provider>
  );
}

export function useSidebar(): SidebarContextValue {
  const context = useContext(SidebarContext);
  if (!context) {
    throw new Error("useSidebar must be used within a SidebarProvider");
  }
  return context;
}
