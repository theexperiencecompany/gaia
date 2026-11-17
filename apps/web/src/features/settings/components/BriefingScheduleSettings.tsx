"use client";

import type { BriefingFrequency } from "@gaia/shared/types";
import { ListBox, Select } from "@heroui/react";
import { formatHour12 } from "@shared/utils";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { BriefsOffBlockedModal } from "@/features/settings/components/BriefsOffBlockedModal";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useBriefingScheduleSettings } from "@/features/settings/hooks/useBriefingScheduleSettings";
import { useQuietHours } from "@/features/settings/hooks/useQuietHours";
import {
  formatHour,
  isQuietHour,
} from "@/features/settings/utils/quietHoursAxis";

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

const FREQUENCIES: { frequency: BriefingFrequency; label: string }[] = [
  { frequency: "daily", label: "Every day" },
  { frequency: "weekdays", label: "Weekdays" },
  { frequency: "weekly_only", label: "Weekly digest only" },
  { frequency: "off", label: "Off" },
];

/** Frequencies that send a daily brief, so its hour means something. */
const WITH_DAILY_BRIEF: ReadonlySet<BriefingFrequency> = new Set([
  "daily",
  "weekdays",
]);

/**
 * "Briefings": how often GAIA sends briefs and the hour the daily one lands,
 * on the user's clock (quiet hours still push it later).
 */
export function BriefingScheduleSettings() {
  const {
    schedule,
    loadFailed,
    saving,
    update,
    briefsOffBlock,
    turnOff,
    keepBriefs,
  } = useBriefingScheduleSettings();
  const { hours: quietHours } = useQuietHours();
  const hasDailyBrief =
    schedule?.frequency !== undefined &&
    WITH_DAILY_BRIEF.has(schedule.frequency);
  const isHeldByQuietHours =
    hasDailyBrief &&
    schedule?.hour !== undefined &&
    !!quietHours &&
    isQuietHour(quietHours, schedule.hour);

  return (
    <SettingsSection
      title="Briefings"
      description={
        loadFailed
          ? "Couldn't load your briefing schedule. Reload the page to try again."
          : "How often GAIA briefs you. The weekly digest arrives Sunday evening."
      }
    >
      <SettingsRow label="Frequency">
        <Select
          className={inputVariants({ size: "sm", className: "w-44" })}
          aria-label="Briefing frequency"
          value={schedule?.frequency ?? null}
          isDisabled={!schedule || saving}
          onChange={(key) => {
            const match = FREQUENCIES.find((f) => f.frequency === key);
            if (match) void update({ frequency: match.frequency });
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
          isHeldByQuietHours && quietHours
            ? `Lands at ${formatHour(quietHours.end_hour)}, when your quiet hours end.`
            : undefined
        }
      >
        <Select
          className={inputVariants({ size: "sm", className: "w-44" })}
          aria-label="Daily brief hour"
          value={schedule?.hour !== undefined ? String(schedule.hour) : null}
          isDisabled={!schedule || saving || !hasDailyBrief}
          onChange={(key) => {
            if (key != null) void update({ hour: Number(key) });
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
                  textValue={formatHour12(hour)}
                />
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
      </SettingsRow>
      <BriefsOffBlockedModal
        block={briefsOffBlock}
        saving={saving}
        onTurnOff={(deliveries) => void turnOff(deliveries)}
        onCancel={keepBriefs}
      />
    </SettingsSection>
  );
}
