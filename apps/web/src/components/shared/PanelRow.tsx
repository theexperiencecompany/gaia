"use client";

import { Button } from "@heroui/button";
import { ArrowDown01Icon, ArrowRight01Icon } from "@icons";
import type { ComponentType, ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PanelRowProps {
  icon: ComponentType<{ className?: string }>;
  label: string;
  summary: string;
  onPress: () => void;
  /** Set for a row that expands in place; left out for a row that opens something else. */
  isExpanded?: boolean;
  /** A control beside the row, such as a switch; it stays reachable while collapsed. */
  trailing?: ReactNode;
  isDimmed?: boolean;
  /** The row's details, shown only while it is expanded. */
  children?: ReactNode;
}

/** One quiet side-panel row: icon, label, a one-line summary, and a disclosure chevron. */
export function PanelRow({
  icon: Icon,
  label,
  summary,
  onPress,
  isExpanded,
  trailing,
  isDimmed = false,
  children,
}: PanelRowProps) {
  const expands = isExpanded !== undefined;
  const Chevron = expands ? ArrowDown01Icon : ArrowRight01Icon;

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2 pr-2">
        <Button
          variant="light"
          radius="lg"
          onPress={onPress}
          aria-expanded={isExpanded}
          className="h-auto min-h-12 min-w-0 flex-1 justify-start gap-3 px-3 py-2 text-left data-[hover=true]:bg-zinc-700/50"
        >
          <Icon className="size-4 shrink-0 text-zinc-400" />
          <span
            className={cn(
              "flex min-w-0 flex-1 flex-col transition-opacity duration-200",
              isDimmed && "opacity-60",
            )}
          >
            <span className="text-xs font-medium text-zinc-300">{label}</span>
            <span
              className={cn(
                "text-xs text-zinc-500",
                isExpanded ? "whitespace-normal text-pretty" : "truncate",
              )}
              title={summary}
            >
              {summary}
            </span>
          </span>
          <Chevron
            className={cn(
              "size-3.5 shrink-0 text-zinc-500 transition-transform duration-200",
              isExpanded && "rotate-180",
            )}
          />
        </Button>
        {trailing}
      </div>
      {isExpanded && children && (
        <div className="flex flex-col gap-3 pb-3 pl-10 pr-3">{children}</div>
      )}
    </div>
  );
}

/** The surface a run of PanelRows sits on, so related rows read as one group. */
export function PanelRowGroup({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col rounded-2xl bg-zinc-800 p-1">{children}</div>
  );
}
