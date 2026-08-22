"use client";

import { Tooltip } from "@heroui/tooltip";
import { InformationCircleIcon } from "@icons";
import {
  USAGE_DANGER_THRESHOLD,
  USAGE_WARN_THRESHOLD,
} from "@shared/constants/usage";

export const ACCENT = "#00bbff"; // brand blue — capacity meters
export const HEALTHY = "#30d158"; // apple green — the activity trend
export const NEAR = "#fbbf24"; // amber — approaching the limit
const HIT = "#ff453a"; // vibrant red — limit reached; only severityColor picks it

export const CARD = "rounded-2xl bg-zinc-900/60";

/** Only the warning states borrow status hues; the "fine" state is the caller's
 * base color, so a glance separates fine / watch-out / maxed without a rainbow.
 * Thresholds are shared with mobile (see @shared/constants/usage). */
export function severityColor(percentage: number, base: string = ACCENT) {
  if (percentage >= USAGE_DANGER_THRESHOLD) return HIT;
  if (percentage >= USAGE_WARN_THRESHOLD) return NEAR;
  return base;
}

export function InfoTip({ text }: { text: string }) {
  return (
    <Tooltip
      content={text}
      placement="top"
      delay={150}
      closeDelay={0}
      classNames={{
        content: "max-w-64 bg-zinc-800 text-xs text-zinc-300 shadow-xl",
      }}
    >
      <span className="cursor-default text-zinc-600 transition-colors hover:text-zinc-400">
        <InformationCircleIcon size={15} />
      </span>
    </Tooltip>
  );
}

/** The pill tab group every usage card uses for its own switches. */
export const TAB_CLASSNAMES = {
  base: "shrink-0",
  tabList: "bg-zinc-800/80 p-0.5",
  cursor: "bg-zinc-700",
  tab: "h-6 px-2.5",
  tabContent:
    "text-xs font-medium text-zinc-500 group-data-[selected=true]:text-zinc-100",
} as const;
