"use client";

import { Tooltip } from "@heroui/react";
import { InformationCircleIcon } from "@icons";
import { overlayVariants } from "@/components/shared/controlVariants";
import { toneVariants } from "@/components/shared/tone";
export const ACCENT = "#00bbff"; // brand blue — capacity meters
export const HEALTHY = "#30d158"; // apple green — the activity trend
export const NEAR = "#fbbf24"; // amber — approaching the limit

export const CARD = "rounded-2xl bg-zinc-900/60";

export function InfoTip({ text }: { text: string }) {
  return (
    <Tooltip delay={150} closeDelay={0}>
      <Tooltip.Trigger
        render={(props) => (
          <span
            {...props}
            className="cursor-default text-zinc-600 transition-colors hover:text-zinc-400"
          />
        )}
      >
        <InformationCircleIcon size={15} />
      </Tooltip.Trigger>
      <Tooltip.Content
        placement="top"
        className={`max-w-64 text-xs shadow-xl ${overlayVariants({ surface: "raised" })} ${toneVariants({ tone: "dim" })}`}
      >
        {text}
      </Tooltip.Content>
    </Tooltip>
  );
}
