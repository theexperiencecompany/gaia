"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Folder01Icon, HardDriveIcon } from "@icons";
import type { ProtectedFolder } from "@shared/desktop-tools";
import { PROTECTED_FOLDERS, useFileAccess } from "../hooks/useFileAccess";

const FOLDER_LABELS: Record<ProtectedFolder, string> = {
  downloads: "Downloads",
  documents: "Documents",
  desktop: "Desktop",
};

/**
 * macOS-only file-access controls for the This Mac card. Per-folder "Allow"
 * buttons trigger the native TCC prompt; "Full Disk Access" deep-links to
 * System Settings. Grants apply to the commands GAIA runs on this Mac
 * (run_on_device). Reliable only on a signed build.
 */
export function FileAccessSection() {
  const { access, busy, requestFolder, openFullDiskAccess } = useFileAccess();

  return (
    <div className="mt-2 rounded-2xl bg-zinc-900 p-3">
      <div className="text-sm font-medium">File access</div>
      <p className="mt-1 text-xs text-zinc-500">
        Commands GAIA runs on this Mac can read and write files. macOS blocks
        the protected folders below until you allow them. Full Disk Access
        grants every file at once — GAIA can then read or write anywhere you ask
        it to.
      </p>

      <div className="mt-3 flex flex-col gap-2">
        {PROTECTED_FOLDERS.map((folder) => {
          const state = access[folder];
          return (
            <div key={folder} className="flex items-center gap-2 text-sm">
              <Folder01Icon className="size-4 text-zinc-400" />
              <span className="min-w-0 flex-1 truncate">
                {FOLDER_LABELS[folder]}
              </span>
              {state === "granted" ? (
                <Chip size="sm" variant="flat" color="success">
                  Allowed
                </Chip>
              ) : (
                <Button
                  size="sm"
                  variant="flat"
                  color={state === "denied" ? "warning" : "primary"}
                  isLoading={busy === folder}
                  onPress={() => void requestFolder(folder)}
                >
                  {state === "denied" ? "Denied — retry" : "Allow"}
                </Button>
              )}
            </div>
          );
        })}

        <div className="flex items-center gap-2 text-sm">
          <HardDriveIcon className="size-4 text-zinc-400" />
          <span className="min-w-0 flex-1 truncate">Full Disk Access</span>
          <Button size="sm" variant="flat" onPress={openFullDiskAccess}>
            Open System Settings
          </Button>
        </div>
      </div>
    </div>
  );
}
