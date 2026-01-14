import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useRef,
} from "react";
import type { DrawerLayoutMethods } from "react-native-gesture-handler/ReanimatedDrawerLayout";

interface SidebarContextValue {
  drawerRef: React.RefObject<DrawerLayoutMethods | null>;
  openSidebar: () => void;
  closeSidebar: () => void;
  toggleSidebar: () => void;
}

const SidebarContext = createContext<SidebarContextValue | null>(null);

interface SidebarProviderProps {
  children: ReactNode;
}

export function SidebarProvider({ children }: SidebarProviderProps) {
  const drawerRef = useRef<DrawerLayoutMethods>(null);

  const openSidebar = useCallback(() => {
    drawerRef.current?.openDrawer();
  }, []);

  const closeSidebar = useCallback(() => {
    drawerRef.current?.closeDrawer();
  }, []);

  const toggleSidebar = useCallback(() => {
    drawerRef.current?.openDrawer();
  }, []);

  return (
    <SidebarContext.Provider
      value={{ drawerRef, openSidebar, closeSidebar, toggleSidebar }}
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
