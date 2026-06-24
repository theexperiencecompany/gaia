/**
 * Trigger settings card — the shared "list rows" layout for every trigger's
 * configuration. One rounded, divided card; each setting is a row with its
 * label on the left and its control on the right (wide controls and a toggle
 * variant included). Keeps every handler visually consistent.
 */

"use client";

import type { ReactNode } from "react";

export function TriggerSettingsCard({ children }: { children: ReactNode }) {
  return (
    <div className="divide-y divide-zinc-800 overflow-hidden rounded-2xl bg-zinc-800/40">
      {children}
    </div>
  );
}

interface TriggerSettingRowProps {
  label: string;
  hint?: string;
  /** Let the control fill the remaining row width (for selects, tag inputs,
      anything richer than a compact picker) instead of a fixed column. */
  wide?: boolean;
  children: ReactNode;
}

export function TriggerSettingRow({
  label,
  hint,
  wide,
  children,
}: TriggerSettingRowProps) {
  return (
    <div className="flex items-start justify-between gap-4 px-4 py-3.5">
      {/* min-h matches a single control row so the label sits centered against
          it, and stays top-aligned when the control grows (e.g. a custom input
          expands below). */}
      <div className="flex min-h-10 min-w-0 flex-col justify-center gap-0.5">
        <span className="text-sm font-medium text-zinc-200">{label}</span>
        {hint ? <span className="text-xs text-zinc-500">{hint}</span> : null}
      </div>
      <div
        className={wide ? "min-w-0 max-w-[26rem] flex-1" : "w-[19rem] shrink-0"}
      >
        {children}
      </div>
    </div>
  );
}
