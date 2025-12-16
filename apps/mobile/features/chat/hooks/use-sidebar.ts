/**
 * useSidebar Hook
 * Manages sidebar open/close state
 */

import { useCallback, useState } from 'react';

export function useSidebar() {
    const [isSidebarOpen, setIsSidebarOpen] = useState(false);

    const openSidebar = useCallback(() => {
        setIsSidebarOpen(true);
    }, []);

    const closeSidebar = useCallback(() => {
        setIsSidebarOpen(false);
    }, []);

    const toggleSidebar = useCallback(() => {
        setIsSidebarOpen(prev => !prev);
    }, []);

    return {
        isSidebarOpen,
        openSidebar,
        closeSidebar,
        toggleSidebar,
    };
}
