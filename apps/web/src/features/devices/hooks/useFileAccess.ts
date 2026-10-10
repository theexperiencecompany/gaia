"use client";

import type { ProtectedFolder } from "@shared/desktop-tools";
import { useCallback, useState } from "react";
import { getElectronAPI } from "@/lib/electron/api";

export type FolderAccessState = "unknown" | "granted" | "denied";

/** The macOS folders GAIA can prompt for, in the order shown on the card. */
export const PROTECTED_FOLDERS: ProtectedFolder[] = [
  "downloads",
  "documents",
  "desktop",
];

/**
 * macOS file-access grants for run_on_device: per-folder TCC prompts plus the
 * Full Disk Access deep link. No-ops off the desktop app (getElectronAPI null).
 */
export function useFileAccess() {
  const [access, setAccess] = useState<
    Record<ProtectedFolder, FolderAccessState>
  >({ downloads: "unknown", documents: "unknown", desktop: "unknown" });
  const [busy, setBusy] = useState<ProtectedFolder | null>(null);

  const requestFolder = useCallback(async (folder: ProtectedFolder) => {
    const api = getElectronAPI();
    if (!api) return;
    setBusy(folder);
    try {
      const result = await api.requestFolderAccess(folder);
      setAccess((prev) => ({
        ...prev,
        [folder]: result.granted ? "granted" : "denied",
      }));
    } finally {
      setBusy(null);
    }
  }, []);

  const openFullDiskAccess = useCallback(() => {
    getElectronAPI()?.openPermissionSettings("full-disk");
  }, []);

  return { access, busy, requestFolder, openFullDiskAccess };
}
