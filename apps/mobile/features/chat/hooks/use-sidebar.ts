/**
 * useSidebar Hook
 * Manages sidebar with DrawerLayout ref
 */

import { useCallback, useRef } from 'react';
import type DrawerLayout from 'react-native-gesture-handler/ReanimatedDrawerLayout';

export function useSidebar() {
    const drawerRef = useRef<DrawerLayout>(null);

    const openSidebar = useCallback(() => {
        drawerRef.current?.openDrawer();
    }, []);

    const closeSidebar = useCallback(() => {
        drawerRef.current?.closeDrawer();
    }, []);

    const toggleSidebar = useCallback(() => {
        const drawer = drawerRef.current;
        if (drawer) {
            // @ts-ignore - DrawerLayout has internal state we can't access
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
