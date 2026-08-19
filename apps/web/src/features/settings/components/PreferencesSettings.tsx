"use client";

import { HilApprovalMode } from "@/features/settings/components/HilApprovalMode";
import { StatusIndicator } from "@/features/settings/components/StatusIndicator";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { getTimezoneList } from "@/utils/timezoneUtils";
import { PreferencesConversationSection } from "./PreferencesConversationSection";
import { PreferencesDangerSection } from "./PreferencesDangerSection";
import { PreferencesIdentitySection } from "./PreferencesIdentitySection";
import type { ModalAction } from "./SettingsMenu";
import { usePreferencesForm } from "./usePreferencesForm";

export default function PreferencesSettings({
  setModalAction,
}: {
  setModalAction: React.Dispatch<React.SetStateAction<ModalAction | null>>;
}) {
  const {
    preferences,
    isUpdating,
    hasUnsavedChanges,
    handleProfessionChange,
    handleResponseStyleChange,
    handleCustomResponseStyleChange,
    handleTimezoneChange,
    handleAutoDetectTimezone,
  } = usePreferencesForm();

  const timezoneOptions = getTimezoneList().map((tz) => ({
    value: tz.value,
    label: tz.formattedLabel,
  }));

  return (
    <SettingsPage>
      <PreferencesIdentitySection
        preferences={preferences}
        timezoneOptions={timezoneOptions}
        isUpdating={isUpdating}
        onProfessionChange={handleProfessionChange}
        onTimezoneChange={handleTimezoneChange}
        onAutoDetectTimezone={handleAutoDetectTimezone}
      />

      <PreferencesConversationSection
        responseStyle={preferences.response_style}
        isUpdating={isUpdating}
        onResponseStyleChange={handleResponseStyleChange}
        onCustomResponseStyleChange={handleCustomResponseStyleChange}
      />

      <HilApprovalMode />

      <PreferencesDangerSection setModalAction={setModalAction} />

      <StatusIndicator
        isUpdating={isUpdating}
        hasUnsavedChanges={hasUnsavedChanges}
      />
    </SettingsPage>
  );
}
