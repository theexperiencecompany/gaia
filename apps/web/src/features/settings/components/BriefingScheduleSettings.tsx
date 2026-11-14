"use client";

import type { BriefingFrequency } from "@gaia/shared/types";
import { Button } from "@heroui/button";
import { Select, SelectItem } from "@heroui/select";
import { formatHour12 } from "@shared/utils";
import { format, parseISO } from "date-fns";
import { paywallCopyFor } from "@/features/pricing/constants";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { BriefsOffBlockedModal } from "@/features/settings/components/BriefsOffBlockedModal";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useBriefingScheduleSettings } from "@/features/settings/hooks/useBriefingScheduleSettings";
import { useQuietHours } from "@/features/settings/hooks/useQuietHours";
import {
  formatHour,
  isQuietHour,
} from "@/features/settings/utils/quietHoursAxis";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

/** The next daily brief, on the reader's clock: "Mon 16 Nov, 7 AM". */
const NEXT_BRIEF_FORMAT = "EEE d MMM, h a";

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
  const { hasEverSubscribed } = useIsPaid();
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);
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
      {schedule?.paused_for_plan && (
        <SettingsRow
          label="Your briefs are paused"
          description="Briefs on a schedule are part of GAIA Pro, so none are sent on the free plan."
        >
          <Button
            size="sm"
            color="primary"
            className="font-medium text-black"
            onPress={() =>
              openUpgradeModal(undefined, {
                dismissible: true,
                source: "settings_briefings",
              })
            }
          >
            {paywallCopyFor(hasEverSubscribed).cta}
          </Button>
        </SettingsRow>
      )}
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
      <SettingsRow
        label="Daily brief at"
        description={
          [
            isHeldByQuietHours && quietHours
              ? `Lands at ${formatHour(quietHours.end_hour)}, when your quiet hours end.`
              : null,
            schedule?.next_daily_brief_at
              ? `Next one ${format(parseISO(schedule.next_daily_brief_at), NEXT_BRIEF_FORMAT)}.`
              : null,
          ]
            .filter(Boolean)
            .join(" ") || undefined
        }
      >
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
      <BriefsOffBlockedModal
        block={briefsOffBlock}
        saving={saving}
        onTurnOff={(deliveries) => void turnOff(deliveries)}
        onCancel={keepBriefs}
      />
    </SettingsSection>
  );
}
