"use client";

import { Chip, Spinner } from "@heroui/react";
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
      {phase.working && <Spinner size="sm" color="accent" />}
      <Chip
        size="sm"
        variant="soft"
        color={
          phase.working || meta.color === "primary" ? "accent" : meta.color
        }
      >
        {meta.label}
      </Chip>
    </div>
  );
}
