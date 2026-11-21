"use client";

import type { ReactNode } from "react";

import { GaiaButton } from "@/components/shared/GaiaButton";

/** A choice of one: a 36px track with the chosen segment raised inside it. */
export default function Segmented<Key extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { key: Key; label: string; icon?: ReactNode }[];
  value: Key;
  onChange: (key: Key) => void;
}) {
  return (
    <fieldset
      aria-label={label}
      className="mx-0 flex h-9 min-w-0 gap-1 rounded-xl border-0 bg-zinc-900 p-1"
    >
      {options.map((option) => {
        const isOn = option.key === value;
        return (
          <GaiaButton
            key={option.key}
            size="sm"
            variant={isOn ? "default-solid" : "text"}
            tone={isOn ? "strong" : "muted"}
            hoverTone={isOn ? "none" : "bright"}
            inset="tight"
            aria-pressed={isOn}
            onPress={() => onChange(option.key)}
            className="h-7 min-w-0 flex-1 gap-1.5 text-[13px] font-medium"
          >
            {option.icon}
            {option.label}
          </GaiaButton>
        );
      })}
    </fieldset>
  );
}
