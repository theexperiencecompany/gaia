"use client";

import { Chip } from "@heroui/chip";
import { Switch } from "@heroui/switch";
import { useEffect, useState } from "react";
import {
  approvalsApi,
  type HilPreferences,
} from "@/features/settings/api/approvalsApi";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { apiService } from "@/lib/api/service";
import { toast } from "@/lib/toast";

const EMPTY_PREFS: HilPreferences = {
  enabled: false,
  always_allowed_tools: [],
};

export default function ApprovalSettings() {
  const [prefs, setPrefs] = useState<HilPreferences>(EMPTY_PREFS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    approvalsApi
      .getHilPreferences()
      .then(setPrefs)
      .catch(() => {
        // silently ignore — defaults keep the toggle usable
      })
      .finally(() => setLoading(false));
  }, []);

  const handleToggle = async (enabled: boolean) => {
    const previous = prefs;
    setPrefs((p) => ({ ...p, enabled }));
    setSaving(true);
    try {
      await approvalsApi.putHilPreferences({ enabled });
      trackEvent(ANALYTICS_EVENTS.SETTINGS_PREFERENCES_CHANGED, {
        setting: "hil_approvals",
        enabled,
      });
    } catch {
      setPrefs(previous);
      toast.error("Failed to update approval preference");
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveTool = async (tool: string) => {
    const previous = prefs;
    const next = prefs.always_allowed_tools.filter((t) => t !== tool);
    setPrefs((p) => ({ ...p, always_allowed_tools: next }));
    try {
      await apiService.put(
        "/approvals/preferences",
        { always_allowed_tools: next },
        { silent: true },
      );
    } catch {
      setPrefs(previous);
      toast.error("Failed to update allowed tools");
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
            isSelected={prefs.enabled}
            isDisabled={loading || saving}
            onValueChange={handleToggle}
            aria-label="Ask before destructive actions"
          />
        </SettingsRow>
      </SettingsSection>

      {prefs.always_allowed_tools.length > 0 && (
        <SettingsSection
          title="Always allowed"
          description="These tools run without asking. Remove one to require approval again."
        >
          <div className="flex flex-wrap gap-2 p-3">
            {prefs.always_allowed_tools.map((tool) => (
              <Chip
                key={tool}
                variant="flat"
                onClose={() => handleRemoveTool(tool)}
              >
                {tool}
              </Chip>
            ))}
          </div>
        </SettingsSection>
      )}
    </SettingsPage>
  );
}
