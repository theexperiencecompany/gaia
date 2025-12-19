import { useCallback, useRef } from "react";
import type { DrawerLayoutMethods } from "react-native-gesture-handler/ReanimatedDrawerLayout";

export function useSidebar() {
  const drawerRef = useRef<DrawerLayoutMethods>(null);

  const openSidebar = useCallback(() => {
    drawerRef.current?.openDrawer();
  }, []);

  const closeSidebar = useCallback(() => {
    drawerRef.current?.closeDrawer();
  }, []);

  const toggleSidebar = useCallback(() => {
    const drawer = drawerRef.current;
    if (drawer) {
      drawer.openDrawer();
    }
  }, []);

  return {
    drawerRef,
    openSidebar,
    closeSidebar,
    toggleSidebar,
  };
}
