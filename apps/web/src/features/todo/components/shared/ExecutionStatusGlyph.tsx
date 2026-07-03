"use client";

import { Spinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import { AlertCircleIcon, CheckmarkCircle02Icon } from "@icons";
import type React from "react";
import { cn } from "@/lib/utils";
import type { ExecutionStatus } from "@/types/features/todoTypes";

interface ExecutionStatusGlyphProps {
  status: ExecutionStatus | null | undefined;
  className?: string;
}

const STATUS_LABEL: Record<ExecutionStatus, string> = {
  proposed: "Proposed by GAIA — awaiting your approval",
  queued: "Queued for GAIA",
  running: "GAIA is working on this",
  needs_you: "Needs your input",
  done: "Done",
  failed: "Failed",
  expired: "Expired",
  dismissed: "Dismissed",
};

/**
 * Small state glyph for a GAIA-assigned todo's `execution_status` — a dot,
 * spinner, or icon, never a labeled `<Chip>` (GAIA todos read as ambient
 * state, not another badge).
 */
export const ExecutionStatusGlyph: React.FC<ExecutionStatusGlyphProps> = ({
  status,
  className,
}) => {
  if (!status) return null;

  let glyph: React.ReactNode;
  switch (status) {
    case "proposed":
      glyph = (
        <span className="block size-2 rounded-full border border-zinc-500" />
      );
      break;
    case "queued":
      glyph = <span className="block size-2 rounded-full bg-zinc-400" />;
      break;
    case "running":
      glyph = <Spinner size="sm" color="primary" />;
      break;
    case "needs_you":
      glyph = <AlertCircleIcon className="size-4 text-amber-400" />;
      break;
    case "done":
      glyph = <CheckmarkCircle02Icon className="size-4 text-green-400" />;
      break;
    case "failed":
      glyph = <AlertCircleIcon className="size-4 text-red-400" />;
      break;
    case "expired":
    case "dismissed":
      glyph = <span className="block size-2 rounded-full bg-zinc-700" />;
      break;
    default:
      glyph = null;
  }

  return (
    <Tooltip content={STATUS_LABEL[status]}>
      <span
        className={cn(
          "inline-flex shrink-0 items-center justify-center",
          className,
        )}
      >
        {glyph}
      </span>
    </Tooltip>
  );
};
