"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { useState } from "react";

import { ChevronDown, ChevronUp } from "@/components/shared/icons";
import { cn } from "@/lib/utils";
import type { BriefingPayload } from "@/types/features/briefingTypes";

export interface BriefingCardProps {
  payload: BriefingPayload;
  /** Controlled collapsed state (e.g. Mission Control using this as its header). */
  collapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
  /** Uncontrolled initial state for standalone use. Ignored if `collapsed` is passed. */
  defaultCollapsed?: boolean;
  className?: string;
}

/** Leading "+"/"-" sniff on a free-string delta — green/red/neutral, nothing fancier. */
function deltaTone(delta: string): string {
  if (delta.startsWith("+")) return "text-emerald-400";
  if (delta.startsWith("-")) return "text-red-400";
  return "text-zinc-400";
}

/**
 * Subtle scrim variance per known mood — a slightly heavier scrim for
 * "packed"/"winback" reads as denser, a lighter one for "clear" reads as
 * airier. Any unrecognized mood (including future ones) falls back to the
 * neutral default rather than breaking.
 */
const MOOD_SCRIM: Record<string, string> = {
  clear: "from-zinc-900/50 via-zinc-900/10 to-zinc-900/50",
  packed: "from-zinc-900/70 via-zinc-900/30 to-zinc-900/70",
  winback: "from-zinc-900/70 via-zinc-900/25 to-zinc-900/70",
  weekly: "from-zinc-900/60 via-zinc-900/20 to-zinc-900/60",
};
const DEFAULT_MOOD_SCRIM = "from-zinc-900/60 via-zinc-900/20 to-zinc-900/60";

export function BriefingCard({
  payload,
  collapsed,
  onCollapsedChange,
  defaultCollapsed = false,
  className,
}: BriefingCardProps) {
  const [uncontrolledCollapsed, setUncontrolledCollapsed] =
    useState(defaultCollapsed);
  const isCollapsed = collapsed ?? uncontrolledCollapsed;

  const toggleCollapsed = () => {
    const next = !isCollapsed;
    if (onCollapsedChange) {
      onCollapsedChange(next);
    } else {
      setUncontrolledCollapsed(next);
    }
  };

  return (
    <div
      className={cn(
        "rounded-2xl bg-zinc-800",
        !isCollapsed && "p-4",
        className,
      )}
    >
      <Masthead
        payload={payload}
        isCollapsed={isCollapsed}
        onToggle={toggleCollapsed}
      />

      {!isCollapsed && (
        <div className="rounded-2xl bg-zinc-900">
          <HeroBand payload={payload} />

          <div className="px-5 pb-5 pt-4">
            <p className="max-w-[60ch] text-sm leading-relaxed text-zinc-300">
              {payload.lede}
            </p>

            {payload.stats.length > 0 && <StatRow stats={payload.stats} />}

            {payload.sections.map((section) => (
              <Section key={section.numeral} section={section} />
            ))}

            <p className="mt-5 text-xs italic text-zinc-500">
              {payload.caption}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

interface MastheadProps {
  payload: BriefingPayload;
  isCollapsed: boolean;
  onToggle: () => void;
}

function Masthead({ payload, isCollapsed, onToggle }: MastheadProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3",
        isCollapsed ? "p-4" : "mb-4",
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-aeonik-display text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
            {payload.kicker}
          </span>
          <span className="text-[11px] text-zinc-600">{payload.date}</span>
        </div>
        {isCollapsed && (
          <p className="mt-1 truncate font-display text-lg italic text-zinc-100">
            {payload.headline}
          </p>
        )}
      </div>
      <Button
        isIconOnly
        size="sm"
        variant="light"
        aria-label={isCollapsed ? "Expand briefing" : "Collapse briefing"}
        onPress={onToggle}
      >
        {isCollapsed ? (
          <ChevronDown className="h-4 w-4 text-zinc-400" />
        ) : (
          <ChevronUp className="h-4 w-4 text-zinc-400" />
        )}
      </Button>
    </div>
  );
}

function HeroBand({ payload }: { payload: BriefingPayload }) {
  return (
    <div className="relative h-40 w-full overflow-hidden rounded-t-2xl sm:h-48">
      <div
        className="absolute inset-0 bg-cover bg-center"
        style={{
          backgroundImage: "url(/images/wallpapers/bands_gradient_1.webp)",
          filter: `hue-rotate(${payload.hue}deg)`,
        }}
      />
      <div
        className={cn(
          "absolute inset-0 bg-gradient-to-t",
          MOOD_SCRIM[payload.mood] ?? DEFAULT_MOOD_SCRIM,
        )}
      />
      <div className="relative flex h-full flex-col justify-end p-5">
        <h2 className="font-display text-2xl italic leading-tight text-zinc-50 sm:text-3xl">
          {payload.headline}
        </h2>
      </div>
    </div>
  );
}

function StatRow({ stats }: { stats: BriefingPayload["stats"] }) {
  return (
    <div className="mt-5 flex divide-x divide-zinc-800 rounded-2xl bg-zinc-800/50">
      {stats.map((stat) => (
        <div key={stat.label} className="flex-1 px-4 py-3 text-center">
          <div className="flex items-baseline justify-center gap-1.5">
            <span className="text-xl font-semibold text-zinc-100">
              {stat.value}
            </span>
            {stat.delta && (
              <span
                className={cn("text-xs font-medium", deltaTone(stat.delta))}
              >
                {stat.delta}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[11px] uppercase tracking-wide text-zinc-500">
            {stat.label}
          </p>
        </div>
      ))}
    </div>
  );
}

function Section({
  section,
}: {
  section: BriefingPayload["sections"][number];
}) {
  return (
    <div className="mt-6">
      <div className="flex items-baseline gap-2">
        <span className="font-display text-sm italic text-zinc-500">
          {section.numeral}
        </span>
        <h3 className="text-sm font-semibold text-zinc-200">{section.title}</h3>
      </div>
      <ul className="mt-2 space-y-1.5">
        {section.items.map((item) => (
          <li key={item.text} className="text-sm leading-relaxed text-zinc-300">
            {item.todo_id ? (
              <Link
                href={`/todos?todoId=${item.todo_id}`}
                className="text-sm text-zinc-300 hover:text-zinc-100"
              >
                {item.text}
              </Link>
            ) : (
              item.text
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
