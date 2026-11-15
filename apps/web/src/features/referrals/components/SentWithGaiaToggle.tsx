"use client";

import { Switch } from "@heroui/switch";
import { SettingsRow } from "@/components/settings/SettingsRow";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useSentWithGaia } from "../hooks/useSentWithGaia";
import { SENT_WITH_GAIA_COPY } from "../referralCopy";

/** Settings → Referrals: opt in to signing GAIA-written mail with your invite link. */
export function SentWithGaiaToggle() {
  const { isEnabled, isSaving, setEnabled } = useSentWithGaia();
  return (
    <SettingsSection>
      <SettingsRow
        label={SENT_WITH_GAIA_COPY.title}
        description={SENT_WITH_GAIA_COPY.body}
      >
        <Switch
          size="sm"
          isSelected={isEnabled}
          isDisabled={isSaving}
          onValueChange={(next) => void setEnabled(next)}
          aria-label={SENT_WITH_GAIA_COPY.title}
        />
      </SettingsRow>
    </SettingsSection>
  );
}
