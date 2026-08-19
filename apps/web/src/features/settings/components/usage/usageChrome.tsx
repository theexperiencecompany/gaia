"use client";

import { Tooltip } from "@heroui/tooltip";
import { InformationCircleIcon } from "@icons";

export {
  ACCENT,
  CARD,
  HEALTHY,
  NEAR,
  severityColor,
  TAB_CLASSNAMES,
} from "./usageChrome.defs";

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
