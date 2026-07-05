"use client";

import { Button } from "@heroui/button";
import { Switch } from "@heroui/switch";
import { useRouter } from "next/navigation";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useHilPreferences } from "@/features/settings/hooks/useHilPreferences";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

export function HilApprovalToggle() {
  const router = useRouter();
  const { prefs, isLoading, isSavingEnabled, setEnabled } = useHilPreferences();

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
    <SettingsSection
      title="Approvals"
      description="Pick which tools ask before running from each integration's tool list."
    >
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
      <SettingsRow
        label="Per-tool approvals"
        description="Fine-tune which tools ask, in each integration's tool list."
      >
        <Button
          size="sm"
          variant="flat"
          className="rounded-xl"
          onPress={() => router.push("/integrations")}
        >
          Open Integrations
        </Button>
      </SettingsRow>
    </SettingsSection>
  );
}
