"use client";

import type { BriefingFrequency } from "@gaia/shared/types";
import { ListBox, Select } from "@heroui/react";
import { formatDate, formatHour } from "@shared/utils";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { LoadError } from "@/components/shared/LoadError";
import { quietHoursLanding } from "@/features/briefing";
import { paywallCopyFor } from "@/features/pricing/constants";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { BriefsOffBlockedModal } from "@/features/settings/components/BriefsOffBlockedModal";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useBriefingScheduleSettings } from "@/features/settings/hooks/useBriefingScheduleSettings";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

const FREQUENCIES: { frequency: BriefingFrequency; label: string }[] = [
  { frequency: "daily", label: "Every day" },
  { frequency: "weekdays", label: "Weekdays" },
  { frequency: "weekly_only", label: "Weekly digest only" },
  { frequency: "off", label: "Off" },
];

/**
 * "Schedule": how often GAIA sends briefs and the hour the daily one lands,
 * on the user's clock (quiet hours still push it later).
 */
export function BriefingScheduleSettings() {
  const {
    schedule,
    loadFailed,
    refetch,
    saving,
    update,
    briefsOffBlock,
    turnOff,
    keepBriefs,
  } = useBriefingScheduleSettings();
  const { hasEverSubscribed } = useIsPaid();
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);
  const sendsDailyBrief = !!schedule?.has_daily_brief;
  const landsAt = schedule ? quietHoursLanding(schedule) : null;

  return (
    <SettingsSection
      title="Schedule"
      description="How often GAIA briefs you. The weekly digest arrives Sunday evening."
    >
      {loadFailed && (
        <LoadError
          layout="inline"
          className="px-4 py-3.5"
          title="Couldn't load your briefing schedule."
          onRetry={refetch}
        />
      )}
      {schedule?.paused_for_plan && (
        <SettingsRow
          label="Your briefs are paused"
          description="Briefs on a schedule are part of GAIA Pro, so none are sent on the free plan."
        >
          <GaiaButton
            size="sm"
            variant="primary"
            className="font-medium"
            onPress={() =>
              openUpgradeModal(undefined, {
                dismissible: true,
                source: "settings_briefings",
              })
            }
          >
            {paywallCopyFor(hasEverSubscribed).cta}
          </GaiaButton>
        </SettingsRow>
      )}
      <SettingsRow label="Frequency">
        <Select
          className={inputVariants({ size: "sm", className: "w-44" })}
          aria-label="Briefing frequency"
          value={schedule?.frequency ?? null}
          isDisabled={!schedule || saving}
          onChange={(key) => {
            const match = FREQUENCIES.find((f) => f.frequency === key);
            if (match) update({ frequency: match.frequency });
          }}
        >
          <Select.Trigger>
            <GaiaSelectValue />
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              {FREQUENCIES.map(({ frequency, label }) => (
                <GaiaListBoxItem
                  key={frequency}
                  id={frequency}
                  textValue={label}
                />
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
      </SettingsRow>
      <SettingsRow
        label="Daily brief at"
        description={
          [
            landsAt === null
              ? null
              : `Lands at ${formatHour(landsAt)}, when your quiet hours end.`,
            schedule?.next_daily_brief_at
              ? `Next one ${formatDate(schedule.next_daily_brief_at, "dayTime")}.`
              : null,
          ]
            .filter(Boolean)
            .join(" ") || undefined
        }
      >
        <Select
          className={inputVariants({ size: "sm", className: "w-44" })}
          aria-label="Daily brief hour"
          value={schedule?.hour !== undefined ? String(schedule.hour) : null}
          isDisabled={!schedule || saving || !sendsDailyBrief}
          onChange={(key) => {
            if (key != null) update({ hour: Number(key) });
          }}
        >
          <Select.Trigger>
            <GaiaSelectValue />
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              {HOURS.map((hour) => (
                <GaiaListBoxItem
                  key={hour}
                  id={String(hour)}
                  textValue={formatHour(hour)}
                />
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
      </SettingsRow>
      <BriefsOffBlockedModal
        block={briefsOffBlock}
        saving={saving}
        onTurnOff={turnOff}
        onCancel={keepBriefs}
      />
    </SettingsSection>
  );
}
