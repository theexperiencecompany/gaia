"use client";

import { useCallback, useEffect, useState } from "react";
import { getElectronAPI } from "@/lib/electron/api";

const noopCleanup = () => {
  // No-op cleanup: no listener was registered outside the desktop app.
};

/**
 * Hook to check if the app is running inside Electron
 * @returns boolean indicating if running in Electron
 */
function useIsElectron(): boolean {
  const [isElectron, setIsElectron] = useState(false);

  useEffect(() => {
    setIsElectron(getElectronAPI() !== null);
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
    getElectronAPI()?.signalReady();
  }, []);

  /**
   * Get the current platform (darwin, win32, linux)
   */
  const getPlatform = useCallback(
    async (): Promise<NodeJS.Platform | null> =>
      getElectronAPI()?.getPlatform() ?? null,
    [],
  );

  /**
   * Get the app version
   */
  const getVersion = useCallback(
    async (): Promise<string | null> => getElectronAPI()?.getVersion() ?? null,
    [],
  );

  /**
   * Open a URL in the system's default browser
   * Used for OAuth flows to open login in external browser
   */
  const openExternal = useCallback((url: string) => {
    getElectronAPI()?.openExternal(url);
  }, []);

  /**
   * Register a callback for auth-redirecting events
   * Fired just before the window navigates to the main app after OAuth
   * Returns a cleanup function to remove the listener
   */
  const onAuthRedirecting = useCallback(
    (callback: () => void): (() => void) =>
      getElectronAPI()?.onAuthRedirecting(callback) ?? noopCleanup,
    [],
  );

  /**
   * Notify the main process that the wake word was detected
   * Sent by the hidden wake-listener window; shows the assistant popup
   */
  const notifyWakeWord = useCallback(() => {
    getElectronAPI()?.notifyWakeWord();
  }, []);

  /**
   * Ask the main process to dismiss the assistant popup
   */
  const dismissPopup = useCallback(() => {
    getElectronAPI()?.dismissPopup();
  }, []);

  /**
   * Resize the assistant popup window to fit its content
   */
  const resizePopup = useCallback((height: number) => {
    getElectronAPI()?.resizePopup(height);
  }, []);

  /**
   * Register a callback for assistant popup activation events
   * Returns a cleanup function to remove the listener
   */
  const onPopupActivate = useCallback(
    (
      callback: (data: { trigger: "wake-word" | "shortcut" }) => void,
    ): (() => void) =>
      getElectronAPI()?.onPopupActivate(callback) ?? noopCleanup,
    [],
  );

  /**
   * Register a callback for assistant popup deactivation events
   * Fired just before the popup window hides, for exit animations
   * Returns a cleanup function to remove the listener
   */
  const onPopupDeactivate = useCallback(
    (callback: () => void): (() => void) =>
      getElectronAPI()?.onPopupDeactivate(callback) ?? noopCleanup,
    [],
  );

  return {
    isElectron,
    signalReady,
    getPlatform,
    getVersion,
    openExternal,
    onAuthRedirecting,
    notifyWakeWord,
    dismissPopup,
    resizePopup,
    onPopupActivate,
    onPopupDeactivate,
  };
}
