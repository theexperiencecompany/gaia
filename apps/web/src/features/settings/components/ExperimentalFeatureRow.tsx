"use client";

import { Chip } from "@heroui/chip";
import { Switch } from "@heroui/switch";
import type { UserFeatureFlagResponse } from "@shared/api/generated";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { FEATURE_STAGE_LABELS } from "@/features/settings/config/featureStages";
import { useFeatureToggle } from "@/features/settings/hooks/useFeatureFlags";

interface ExperimentalFeatureRowProps {
  feature: UserFeatureFlagResponse;
}

export function ExperimentalFeatureRow({
  feature,
}: ExperimentalFeatureRowProps) {
  const { setEnabled, isSaving } = useFeatureToggle();

  return (
    <SettingsRow
      label={feature.label}
      description={
        <>
          {feature.description}
          {feature.unavailable_reason && (
            <span className="mt-1 block text-amber-400">
              {feature.unavailable_reason}
            </span>
          )}
        </>
      }
    >
      <div className="flex items-center gap-3">
        <Chip size="sm" variant="flat" color="warning">
          {FEATURE_STAGE_LABELS[feature.stage]}
        </Chip>
        <Switch
          size="sm"
          isSelected={feature.enabled}
          isDisabled={!feature.available || isSaving}
          onValueChange={(enabled) => setEnabled(feature.key, enabled)}
          aria-label={`Turn ${feature.label} ${feature.enabled ? "off" : "on"}`}
        />
      </div>
    </SettingsRow>
  );
}
