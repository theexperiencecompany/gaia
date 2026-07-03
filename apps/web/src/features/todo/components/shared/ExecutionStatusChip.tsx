"use client";

import { Chip } from "@heroui/chip";
import type React from "react";
import type { ExecutionStatus } from "@/types/features/todoTypes";

type ChipColor = "warning" | "default" | "primary" | "success" | "danger";

const STATUS: Record<ExecutionStatus, { label: string; color: ChipColor }> = {
  proposed: { label: "Awaiting approval", color: "warning" },
  queued: { label: "Queued", color: "default" },
  running: { label: "Working", color: "primary" },
  needs_you: { label: "Needs you", color: "warning" },
  done: { label: "Done", color: "success" },
  failed: { label: "Failed", color: "danger" },
  expired: { label: "Expired", color: "default" },
  dismissed: { label: "Dismissed", color: "default" },
};

/**
 * Text chip for a GAIA todo's `execution_status`. Used in the detail sidebar,
 * where the full lifecycle state should read at a glance (the list row keeps
 * the compact glyph instead).
 */
export const ExecutionStatusChip: React.FC<{
  status: ExecutionStatus | null | undefined;
}> = ({ status }) => {
  if (!status) return null;
  const { label, color } = STATUS[status];
  return (
    <Chip size="sm" radius="sm" color={color} variant="flat">
      {label}
    </Chip>
  );
};
