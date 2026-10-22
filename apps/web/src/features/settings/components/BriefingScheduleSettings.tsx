"use client";

import type { BriefingFrequency } from "@gaia/shared/types";
import { Select, SelectItem } from "@heroui/select";
import { formatHour12 } from "@shared/utils";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useBriefingScheduleSettings } from "@/features/settings/hooks/useBriefingScheduleSettings";

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
  const { schedule, loadFailed, saving, update } =
    useBriefingScheduleSettings();
  const hasDailyBrief =
    schedule?.frequency !== undefined &&
    WITH_DAILY_BRIEF.has(schedule.frequency);

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
          size="sm"
          className="w-44"
          aria-label="Briefing frequency"
          selectedKeys={schedule?.frequency ? [schedule.frequency] : []}
          isDisabled={!schedule || saving}
          onSelectionChange={(keys) => {
            const next = Array.from(keys)[0];
            const match = FREQUENCIES.find((f) => f.frequency === next);
            if (match) void update({ frequency: match.frequency });
          }}
        >
          {FREQUENCIES.map(({ frequency, label }) => (
            <SelectItem key={frequency}>{label}</SelectItem>
          ))}
        </Select>
      </SettingsRow>
      <SettingsRow label="Daily brief at">
        <Select
          size="sm"
          className="w-44"
          aria-label="Daily brief hour"
          selectedKeys={
            schedule?.hour !== undefined ? [String(schedule.hour)] : []
          }
          isDisabled={!schedule || saving || !hasDailyBrief}
          onSelectionChange={(keys) => {
            const next = Array.from(keys)[0];
            if (next !== undefined) void update({ hour: Number(next) });
          }}
        >
          {HOURS.map((hour) => (
            <SelectItem key={String(hour)}>{formatHour12(hour)}</SelectItem>
          ))}
        </Select>
      </SettingsRow>
    </SettingsSection>
  );
}
