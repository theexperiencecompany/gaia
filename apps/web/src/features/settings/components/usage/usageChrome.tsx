"use client";

import { Tooltip } from "@heroui/tooltip";
import { InformationCircleIcon } from "@icons";
export const ACCENT = "#00bbff"; // brand blue — capacity meters
export const HEALTHY = "#30d158"; // apple green — the activity trend
export const NEAR = "#fbbf24"; // amber — approaching the limit

export const CARD = "rounded-2xl bg-zinc-900/60";

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
