"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import type {
  DesktopPermissionPane,
  DesktopPermissionStatus,
} from "@shared/desktop-tools";
import { useCallback, useEffect, useState } from "react";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { getElectronAPI } from "@/lib/electron/api";
import { toast } from "@/lib/toast";

/** Poll interval while the page is visible — grants happen in System Settings. */
const REFRESH_INTERVAL_MS = 2000;

interface PermissionRowConfig {
  pane: DesktopPermissionPane;
  label: string;
  description: string;
  /** Whether the OS offers a real prompt (vs Settings-only granting). */
  promptable: boolean;
}

const PERMISSION_ROWS: PermissionRowConfig[] = [
  {
    pane: "microphone",
    label: "Microphone",
    description: 'Needed for the "Hey GAIA" wake word and voice input.',
    promptable: true,
  },
  {
    pane: "screen",
    label: "Screen Recording",
    description:
      "Lets GAIA see your screen when you ask about it. macOS only allows granting this in System Settings.",
    promptable: false,
  },
  {
    pane: "accessibility",
    label: "Accessibility",
    description:
      "Required for upcoming computer-use features (clicking and typing for you).",
    promptable: true,
  },
];

function statusChip(granted: boolean, known: boolean) {
  if (!known) {
    return (
      <Chip size="sm" variant="flat" classNames={{ content: "text-xs" }}>
        Unknown
      </Chip>
    );
  }
  return granted ? (
    <Chip
      size="sm"
      variant="flat"
      color="success"
      classNames={{
        base: "bg-success/15",
        content: "text-xs text-emerald-400",
      }}
    >
      Granted
    </Chip>
  ) : (
    <Chip
      size="sm"
      variant="flat"
      color="danger"
      classNames={{ base: "bg-red-500/15", content: "text-xs text-red-400" }}
    >
      Not granted
    </Chip>
  );
}

/** Live permission status rows with grant / open-settings actions. */
export function DesktopPermissions() {
  const [status, setStatus] = useState<DesktopPermissionStatus | null>(null);
  const [settingsOpened, setSettingsOpened] = useState(false);

  const refresh = useCallback(async () => {
    const api = getElectronAPI();
    if (!api) return;
    try {
      setStatus(await api.getDesktopPermissions());
    } catch {
      // Transient IPC failure during polling — keep the last known status.
    }
  }, []);

  useEffect(() => {
    void refresh();
    // Instant update when the user comes back from System Settings,
    // with polling as a fallback while the page stays visible.
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, REFRESH_INTERVAL_MS);
    return () => {
      window.removeEventListener("focus", onFocus);
      clearInterval(interval);
    };
  }, [refresh]);

  const handleRequest = async (row: PermissionRowConfig) => {
    const api = getElectronAPI();
    if (!api) return;
    try {
      if (row.promptable) {
        setStatus(await api.requestDesktopPermission(row.pane));
      } else {
        api.openPermissionSettings(row.pane);
        setSettingsOpened(true);
      }
    } catch {
      toast.error("Could not update that permission. Please try again.");
    }
  };

  return (
    <>
      {PERMISSION_ROWS.map((row) => {
        const value = status?.[row.pane];
        const known = value !== undefined && value !== "unknown";
        const granted = value === "granted";
        // macOS only applies a Screen Recording grant to a freshly launched
        // process, so the running app keeps reporting "denied" — offer a
        // restart once the user has been to System Settings.
        const needsRestart =
          row.pane === "screen" && settingsOpened && !granted;
        return (
          <SettingsRow
            key={row.pane}
            label={row.label}
            description={
              needsRestart
                ? "Enabled it in System Settings? Restart GAIA to apply — macOS only applies this permission on launch."
                : row.description
            }
          >
            <div className="flex items-center gap-2">
              {statusChip(granted, known)}
              {!granted && (
                <Button
                  size="sm"
                  variant="flat"
                  className="rounded-xl"
                  onPress={() => void handleRequest(row)}
                >
                  {row.promptable ? "Allow" : "Open Settings"}
                </Button>
              )}
              {needsRestart && (
                <Button
                  size="sm"
                  variant="flat"
                  color="primary"
                  className="rounded-xl"
                  onPress={() => getElectronAPI()?.relaunchDesktopApp()}
                >
                  Restart GAIA
                </Button>
              )}
            </div>
          </SettingsRow>
        );
      })}
    </>
  );
}
