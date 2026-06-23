/**
 * IntervalPicker — preset segmented control with a custom value (NumberInput +
 * minutes/hours/days unit). The value is always stored as a number of minutes,
 * so handlers can drop it straight into trigger_config.
 */

"use client";

import { NumberInput } from "@heroui/number-input";
import { Select, SelectItem } from "@heroui/select";
import { Tab, Tabs } from "@heroui/tabs";
import { useState } from "react";

const UNIT_FACTOR = { minutes: 1, hours: 60, days: 1440 } as const;
type TimeUnit = keyof typeof UNIT_FACTOR;

const DEFAULT_PRESETS = [5, 15, 30, 60];
const MAX_MINUTES = 1440 * 30; // 30 days

function presetLabel(mins: number): string {
  if (mins % 1440 === 0) return `${mins / 1440}d`;
  if (mins % 60 === 0) return `${mins / 60}h`;
  return `${mins}m`;
}

function splitMinutes(mins: number): { amount: number; unit: TimeUnit } {
  if (mins % 1440 === 0) return { amount: mins / 1440, unit: "days" };
  if (mins % 60 === 0) return { amount: mins / 60, unit: "hours" };
  return { amount: mins, unit: "minutes" };
}

interface IntervalPickerProps {
  value: number; // minutes
  onChange: (minutes: number) => void;
  presets?: number[];
}

export function IntervalPicker({
  value,
  onChange,
  presets = DEFAULT_PRESETS,
}: IntervalPickerProps) {
  const isPreset = presets.includes(value);
  const [customMode, setCustomMode] = useState(!isPreset);
  const initial = splitMinutes(value);
  const [amount, setAmount] = useState(initial.amount);
  const [unit, setUnit] = useState<TimeUnit>(initial.unit);

  const applyCustom = (nextAmount: number, nextUnit: TimeUnit) => {
    const amt = Number.isNaN(nextAmount) ? 1 : Math.max(1, nextAmount);
    setAmount(amt);
    setUnit(nextUnit);
    onChange(Math.min(MAX_MINUTES, amt * UNIT_FACTOR[nextUnit]));
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
            <SelectItem key="minutes">minutes</SelectItem>
            <SelectItem key="hours">hours</SelectItem>
            <SelectItem key="days">days</SelectItem>
          </Select>
        </div>
      )}
    </div>
  );
}
