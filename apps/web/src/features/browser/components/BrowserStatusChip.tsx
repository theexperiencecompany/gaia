"use client";

import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import type { BrowserCardPhase } from "../types";
import { BROWSER_STATUS_META } from "../utils";

/** A browser card's status as the chat card and the side panel both show it. */
export function BrowserStatusChip({
  phase,
}: {
  phase: Pick<BrowserCardPhase, "status" | "working">;
}) {
  const meta = BROWSER_STATUS_META[phase.status];
  return (
    <div className="flex items-center gap-1.5">
      {phase.working && (
        <Spinner size="sm" color="current" className="text-[#00bbff]" />
      )}
      <Chip
        size="sm"
        variant="flat"
        color={meta.color}
        // Browser accent is #00bbff — apply it to the live "Working" state.
        classNames={
          phase.working
            ? { base: "!bg-[#00bbff]/15", content: "!text-[#00bbff]" }
            : undefined
        }
      >
        {meta.label}
      </Chip>
    </div>
  );
}
