"use client";

import type { DesktopSettingsSnapshot } from "@shared/desktop-tools";
import { useCallback, useEffect, useState } from "react";
import { AppIconPicker } from "@/features/settings/components/desktop/AppIconPicker";
import { DesktopPermissions } from "@/features/settings/components/desktop/DesktopPermissions";
import { ShortcutRecorder } from "@/features/settings/components/desktop/ShortcutRecorder";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useElectron } from "@/hooks/useElectron";
import { getElectronAPI } from "@/lib/electron/api";
import { toast } from "@/lib/toast";

/** Desktop-app preferences: shortcut, dock icon, and OS permissions. */
export default function DesktopSettings() {
  const { isElectron } = useElectron();
  const [snapshot, setSnapshot] = useState<DesktopSettingsSnapshot | null>(
    null,
  );

  useEffect(() => {
    const api = getElectronAPI();
    if (!api) return;
    api
      .getDesktopSettings()
      .then(setSnapshot)
      .catch(() => toast.error("Could not load desktop settings"));
  }, []);

  const handleRecordShortcut = useCallback(
    async (accelerator: string): Promise<boolean> => {
      const api = getElectronAPI();
      if (!api) return false;
      try {
        const result = await api.setPopupShortcut(accelerator);
        setSnapshot((prev) =>
          prev
            ? {
                ...prev,
                settings: { ...prev.settings, popupShortcut: result.shortcut },
              }
            : prev,
        );
        if (!result.ok && result.error) {
          toast.error(result.error);
        }
        return result.ok;
      } catch {
        toast.error("Could not update the shortcut");
        return false;
      }
    },
    [],
  );

  const handleSelectIcon = useCallback(async (id: string) => {
    const api = getElectronAPI();
    if (!api) return;
    try {
      const ok = await api.setAppIcon(id);
      if (ok) {
        setSnapshot((prev) =>
          prev
            ? { ...prev, settings: { ...prev.settings, appIcon: id } }
            : prev,
        );
      } else {
        toast.error("Could not apply that icon");
      }
    } catch {
      toast.error("Could not apply that icon");
    }
  }, []);

  if (!isElectron) {
    return (
      <SettingsPage>
        <SettingsSection title="Desktop">
          <SettingsRow
            label="Only available in the desktop app"
            description="Download GAIA for desktop to configure shortcuts, app icons, and permissions."
          />
        </SettingsSection>
      </SettingsPage>
    );
  }

  return (
    <SettingsPage>
      <SettingsSection
        title="Shortcuts"
        description="Summon the assistant popup from anywhere."
      >
        <SettingsRow
          label="Toggle assistant popup"
          description='Works alongside the "Hey GAIA" wake word.'
        >
          {snapshot && (
            <ShortcutRecorder
              value={snapshot.settings.popupShortcut}
              onRecord={handleRecordShortcut}
            />
          )}
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="App Icon"
        description="Pick the icon GAIA shows in your Dock."
      >
        {snapshot && (
          <AppIconPicker
            icons={snapshot.icons}
            selectedId={snapshot.settings.appIcon}
            onSelect={(id) => {
              handleSelectIcon(id);
            }}
          />
        )}
      </SettingsSection>

      <SettingsSection
        title="Permissions"
        description="What GAIA is allowed to do on this Mac."
      >
        <DesktopPermissions />
      </SettingsSection>
    </SettingsPage>
  );
}
