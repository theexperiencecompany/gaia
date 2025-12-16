"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Auth callback data from deep link
 */
interface AuthCallbackData {
  token: string;
}

/**
 * Type definition for the Electron API exposed via preload
 */
interface ElectronAPI {
  getPlatform: () => Promise<NodeJS.Platform>;
  getVersion: () => Promise<string>;
  isElectron: boolean;
  signalReady: () => void;
  openExternal: (url: string) => void;
  onAuthCallback: (callback: (data: AuthCallbackData) => void) => () => void;
}

/**
 * Type guard to check if window.api exists and is the Electron API
 */
function hasElectronAPI(
  window: Window,
): window is Window & { api: ElectronAPI } {
  return (
    typeof window !== "undefined" &&
    "api" in window &&
    typeof window.api === "object" &&
    window.api !== null &&
    "isElectron" in window.api &&
    window.api.isElectron === true
  );
}

/**
 * Hook to check if the app is running inside Electron
 * @returns boolean indicating if running in Electron
 */
export function useIsElectron(): boolean {
  const [isElectron, setIsElectron] = useState(false);

  useEffect(() => {
    // Check if running in Electron by looking for window.api
    const electronDetected =
      typeof window !== "undefined" && hasElectronAPI(window);
    setIsElectron(electronDetected);
  }, []);

  return isElectron;
}

/**
 * Hook providing Electron-specific utilities
 * @returns Object with isElectron flag and utility methods
 */
export function useElectron() {
  const isElectron = useIsElectron();

  /**
   * Signal to the Electron main process that the renderer is ready
   * This closes the splash screen and shows the main window
   */
  const signalReady = useCallback(() => {
    if (typeof window !== "undefined" && hasElectronAPI(window)) {
      window.api.signalReady();
    }
  }, []);

  /**
   * Get the current platform (darwin, win32, linux)
   */
  const getPlatform = useCallback(async (): Promise<NodeJS.Platform | null> => {
    if (typeof window !== "undefined" && hasElectronAPI(window)) {
      return window.api.getPlatform();
    }
    return null;
  }, []);

  /**
   * Get the app version
   */
  const getVersion = useCallback(async (): Promise<string | null> => {
    if (typeof window !== "undefined" && hasElectronAPI(window)) {
      return window.api.getVersion();
    }
    return null;
  }, []);

  /**
   * Open a URL in the system's default browser
   * Used for OAuth flows to open login in external browser
   */
  const openExternal = useCallback((url: string) => {
    if (typeof window !== "undefined" && hasElectronAPI(window)) {
      window.api.openExternal(url);
    }
  }, []);

  /**
   * Register a callback for auth deep link events
   * Returns a cleanup function to remove the listener
   */
  const onAuthCallback = useCallback(
    (callback: (data: AuthCallbackData) => void): (() => void) => {
      if (typeof window !== "undefined" && hasElectronAPI(window)) {
        return window.api.onAuthCallback(callback);
      }
      return () => {}; // No-op cleanup if not in Electron
    },
    [],
  );

  return {
    isElectron,
    signalReady,
    getPlatform,
    getVersion,
    openExternal,
    onAuthCallback,
  };
}
