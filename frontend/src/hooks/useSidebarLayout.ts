/**
 * Sidebar Layout Hook
 * Manages sidebar layout preference with localStorage persistence
 */

import { useState, useEffect, useCallback } from 'react';
import {
    SidebarLayoutType,
    SIDEBAR_LAYOUTS,
    DEFAULT_SIDEBAR_LAYOUT,
    SidebarLayoutConfig
} from '@/config/sidebarLayouts';

const STORAGE_KEY = 'aexy-sidebar-layout';

export function useSidebarLayout() {
    const [layout, setLayoutState] = useState<SidebarLayoutType>(DEFAULT_SIDEBAR_LAYOUT);
    const [isLoaded, setIsLoaded] = useState(false);

    // Load from localStorage on mount
    useEffect(() => {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored && (stored === 'grouped' || stored === 'flat')) {
            setLayoutState(stored as SidebarLayoutType);
        }
        setIsLoaded(true);
    }, []);

    // Set layout and persist to localStorage
    const setLayout = useCallback((newLayout: SidebarLayoutType) => {
        setLayoutState(newLayout);
        localStorage.setItem(STORAGE_KEY, newLayout);
    }, []);

    // Get the current layout config
    const layoutConfig: SidebarLayoutConfig = SIDEBAR_LAYOUTS[layout];

    return {
        layout,
        setLayout,
        layoutConfig,
        isLoaded,
        availableLayouts: SIDEBAR_LAYOUTS,
    };
}
