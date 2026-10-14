"use client";

import { useEffect, useState } from "react";
import { getElectronAPI } from "@/lib/electron/api";

/**
 * The Electron main-process platform (`"darwin"` / `"linux"` / `"win32"`), or
 * null in the browser and until it resolves. This is the accurate source for
 * gating desktop-only, OS-specific UI (the browser's `navigator.platform` can't
 * reliably tell Linux from Windows).
 */
export function useDesktopPlatform(): NodeJS.Platform | null {
  const [platform, setPlatform] = useState<NodeJS.Platform | null>(null);
  useEffect(() => {
    const api = getElectronAPI();
    if (!api) return;
    let cancelled = false;
    void api.getPlatform().then((resolved) => {
      if (!cancelled) setPlatform(resolved);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return platform;
}

/** Whether the in-app "connect this computer" card is supported on this desktop
 * platform. macOS and Linux for now — Windows needs a drive-aware file root and
 * its own PATH handling first. */
export function isThisDeviceSupported(
  platform: NodeJS.Platform | null,
): boolean {
  return platform === "darwin" || platform === "linux";
}

/** Human label for the machine the desktop app runs on. */
export function thisDeviceLabel(platform: NodeJS.Platform | null): string {
  return platform === "darwin" ? "This Mac" : "This computer";
}
