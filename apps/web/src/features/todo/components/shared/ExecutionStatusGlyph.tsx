"use client";

import { Spinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import type React from "react";
import { StatusGlyph } from "@/components/shared/StatusGlyph";
import { cn } from "@/lib/utils";
import type { ExecutionStatus } from "@/types/features/todoTypes";

interface ExecutionStatusGlyphProps {
  status: ExecutionStatus | null | undefined;
  /** Mark size in px — 16 inline next to text, ~20 as a row's leading mark. */
  size?: number;
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
 * Compact state mark for a GAIA todo's `execution_status` in list rows —
 * the same glyph language as the Today dashboard, sized down. Terminal
 * expired/dismissed states stay a muted dot; running is a real Spinner.
 */
export const ExecutionStatusGlyph: React.FC<ExecutionStatusGlyphProps> = ({
  status,
  size = 16,
  className,
}) => {
  if (!status) return null;

  let glyph: React.ReactNode;
  switch (status) {
    case "proposed":
      glyph = <StatusGlyph kind="proposed" size={size} />;
      break;
    case "queued":
      glyph = <StatusGlyph kind="queued" size={size} />;
      break;
    case "running":
      glyph = <Spinner size="sm" color="primary" />;
      break;
    case "needs_you":
      glyph = <StatusGlyph kind="blocked" size={size} />;
      break;
    case "done":
      glyph = <StatusGlyph kind="done" size={size} />;
      break;
    case "failed":
      glyph = <StatusGlyph kind="failed" size={size} />;
      break;
    case "expired":
    case "dismissed":
      glyph = <span className="block size-2 rounded-full bg-zinc-700" />;
      break;
    default:
      glyph = null;
  }

  return (
    <Tooltip content={STATUS_LABEL[status]} size="sm" delay={200}>
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
