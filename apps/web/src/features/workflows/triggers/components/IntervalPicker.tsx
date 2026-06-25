/**
 * IntervalPicker — preset segmented control with a custom value (NumberInput +
 * minutes/hours/days unit). The value is always stored as a number of minutes,
 * so handlers can drop it straight into trigger_config.
 *
 * `maxMinutes` caps the value (default 1440 — the backend hard-limit for the
 * gmail poll interval and calendar lead time). Units are only offered when at
 * least two of them fit under the cap, and both the unit and the typed amount
 * are clamped so the picker can never emit a value the API would reject.
 */

"use client";

import { NumberInput } from "@heroui/number-input";
import { Select, SelectItem } from "@heroui/select";
import { Tab, Tabs } from "@heroui/tabs";
import { useState } from "react";

const UNIT_FACTOR = { minutes: 1, hours: 60, days: 1440 } as const;
type TimeUnit = keyof typeof UNIT_FACTOR;
const UNIT_ORDER: TimeUnit[] = ["days", "hours", "minutes"];

const DEFAULT_PRESETS = [5, 15, 30, 60];
const DEFAULT_MAX_MINUTES = 1440; // 1 day

function presetLabel(mins: number): string {
  if (mins % 1440 === 0) return `${mins / 1440}d`;
  if (mins % 60 === 0) return `${mins / 60}h`;
  return `${mins}m`;
}

// Offer a unit only when at least two of it fit under the cap (so "days" with a
// 1-day max isn't a one-value dead end).
function availableUnits(maxMinutes: number): TimeUnit[] {
  return (["minutes", "hours", "days"] as TimeUnit[]).filter(
    (u) => u === "minutes" || maxMinutes >= UNIT_FACTOR[u] * 2,
  );
}

function splitMinutes(
  mins: number,
  units: TimeUnit[],
): { amount: number; unit: TimeUnit } {
  for (const u of UNIT_ORDER) {
    if (units.includes(u) && mins % UNIT_FACTOR[u] === 0) {
      return { amount: mins / UNIT_FACTOR[u], unit: u };
    }
  }
  return { amount: mins, unit: "minutes" };
}

interface IntervalPickerProps {
  value: number; // minutes
  onChange: (minutes: number) => void;
  presets?: number[];
  maxMinutes?: number;
}

export function IntervalPicker({
  value,
  onChange,
  presets = DEFAULT_PRESETS,
  maxMinutes = DEFAULT_MAX_MINUTES,
}: Readonly<IntervalPickerProps>) {
  const units = availableUnits(maxMinutes);
  const isPreset = presets.includes(value);
  const [customMode, setCustomMode] = useState(!isPreset);
  const initial = splitMinutes(value, units);
  const [amount, setAmount] = useState(initial.amount);
  const [unit, setUnit] = useState<TimeUnit>(initial.unit);

  const maxAmountFor = (u: TimeUnit) =>
    Math.max(1, Math.floor(maxMinutes / UNIT_FACTOR[u]));

  const applyCustom = (nextAmount: number, nextUnit: TimeUnit) => {
    const max = maxAmountFor(nextUnit);
    const amt = Number.isNaN(nextAmount)
      ? 1
      : Math.min(max, Math.max(1, nextAmount));
    setAmount(amt);
    setUnit(nextUnit);
    onChange(amt * UNIT_FACTOR[nextUnit]);
  };

  return (
    <div className="space-y-2">
      <Tabs
        aria-label="Interval"
        selectedKey={customMode ? "custom" : String(value)}
        onSelectionChange={(k) => {
          const key = String(k);
          if (key === "custom") {
            setCustomMode(true);
          } else {
            setCustomMode(false);
            onChange(Number(key));
          }
        }}
        fullWidth
        classNames={{
          tabList: "rounded-xl bg-zinc-800/60 p-1",
          cursor: "rounded-lg bg-zinc-700 shadow-sm",
          tabContent:
            "font-medium text-zinc-400 group-data-[selected=true]:text-white",
          panel: "hidden",
        }}
      >
        {presets.map((p) => (
          <Tab key={String(p)} title={presetLabel(p)} />
        ))}
        <Tab key="custom" title="Custom" />
      </Tabs>
      {customMode && (
        <div className="flex items-center gap-2">
          <NumberInput
            aria-label="Custom interval"
            minValue={1}
            maxValue={maxAmountFor(unit)}
            hideStepper
            value={amount}
            onValueChange={(n) => applyCustom(n, unit)}
            className="flex-1"
          />
          <Select
            aria-label="Unit"
            selectedKeys={new Set([unit])}
            onSelectionChange={(keys) =>
              applyCustom(amount, Array.from(keys)[0] as TimeUnit)
            }
            disallowEmptySelection
            className="w-32 shrink-0"
            classNames={{ popoverContent: "min-w-fit" }}
          >
            {units.map((u) => (
              <SelectItem key={u}>{u}</SelectItem>
            ))}
          </Select>
        </div>
      )}
    </div>
  );
}
