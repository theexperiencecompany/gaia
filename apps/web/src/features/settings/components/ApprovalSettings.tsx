"use client";

import { Chip } from "@heroui/chip";
import { Switch } from "@heroui/switch";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useHilPreferences } from "@/features/settings/hooks/useHilPreferences";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

export default function ApprovalSettings() {
  const { prefs, isLoading, isSavingEnabled, setEnabled, resetTool } =
    useHilPreferences();
  const overrides = Object.entries(prefs?.tool_overrides ?? {});

  const handleToggle = async (enabled: boolean) => {
    try {
      await setEnabled(enabled);
      trackEvent(ANALYTICS_EVENTS.SETTINGS_PREFERENCES_CHANGED, {
        setting: "hil_approvals",
        enabled,
      });
    } catch {
      toast.error("Failed to update approval preference");
    }
  };

  return (
    <SettingsPage>
      <SettingsSection description="GAIA pauses and asks you before sending, deleting, or posting anything on your behalf.">
        <SettingsRow
          label="Ask before destructive actions"
          description="Approve or decline before GAIA sends, deletes, or posts on your behalf."
        >
          <Switch
            size="sm"
            isSelected={prefs?.enabled ?? false}
            isDisabled={isLoading || isSavingEnabled}
            onValueChange={handleToggle}
            aria-label="Ask before destructive actions"
          />
        </SettingsRow>
      </SettingsSection>

      {overrides.length > 0 && (
        <SettingsSection
          title="Custom per-tool rules"
          description="Overrides you set from an integration's tool list. Remove one to return it to the default."
        >
          <div className="flex flex-wrap gap-2 p-3">
            {overrides.map(([tool, ask]) => (
              <Chip key={tool} variant="flat" onClose={() => resetTool(tool)}>
                {tool} · {ask ? "always ask" : "never ask"}
              </Chip>
            ))}
          </div>
        </SettingsSection>
      )}
    </SettingsPage>
  );
}
