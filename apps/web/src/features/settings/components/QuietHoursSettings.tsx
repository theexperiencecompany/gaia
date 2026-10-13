"use client";

import type { QuietHours } from "@gaia/shared/types";
import { Select, SelectItem } from "@heroui/select";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useQuietHoursSettings } from "@/features/settings/hooks/useQuietHoursSettings";

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

/** "22" -> "10:00 PM" in the viewer's locale. */
function hourLabel(hour: number): string {
  return new Date(2000, 0, 1, hour).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

const EDGES: { edge: keyof QuietHours; label: string }[] = [
  { edge: "start_hour", label: "Starts at" },
  { edge: "end_hour", label: "Ends at" },
];

/**
 * "Quiet hours": the daily window, on the user's clock, in which GAIA holds
 * proactive messages instead of sending them.
 */
export function QuietHoursSettings() {
  const { quietHours, saving, setEdge } = useQuietHoursSettings();

  return (
    <SettingsSection
      title="Quiet hours"
      description="GAIA holds proactive messages during this window, on your clock."
    >
      {EDGES.map(({ edge, label }) => (
        <SettingsRow key={edge} label={label}>
          <Select
            size="sm"
            className="w-36"
            aria-label={`Quiet hours ${label.toLowerCase()}`}
            selectedKeys={quietHours ? [String(quietHours[edge])] : []}
            isDisabled={!quietHours || saving}
            onSelectionChange={(keys) => {
              const next = Array.from(keys)[0];
              if (next !== undefined) void setEdge(edge, Number(next));
            }}
          >
            {HOURS.map((hour) => (
              <SelectItem key={String(hour)}>{hourLabel(hour)}</SelectItem>
            ))}
          </Select>
        </SettingsRow>
      ))}
    </SettingsSection>
  );
}
