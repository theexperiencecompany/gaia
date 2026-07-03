"use client";

import { Chip } from "@heroui/chip";
import { AiBrainIcon, TargetIcon } from "@icons";

interface GaiaTodoBadgeProps {
  kind?: "task" | "goal";
  assignee?: string;
  vfsPath?: string | null;
}

/**
 * The identity chip for a todo: "Goal" for a goal lane, "Created by GAIA" for a
 * GAIA-assigned task. Shared so the list row and the detail sidebar render the
 * exact same badge and never drift.
 */
export function GaiaTodoBadge({ kind, assignee, vfsPath }: GaiaTodoBadgeProps) {
  if (kind === "goal") {
    return (
      <Chip
        className="flex items-center px-1 text-warning"
        size="sm"
        radius="sm"
        color="warning"
        variant="flat"
        startContent={<TargetIcon width={14} height={14} className="mx-1" />}
      >
        Goal
      </Chip>
    );
  }
  // `vfs_path` is a fallback signal during the assignee migration window.
  if (assignee === "gaia" || vfsPath) {
    return (
      <Chip
        className="flex items-center px-1 text-primary"
        size="sm"
        radius="sm"
        color="primary"
        variant="flat"
        startContent={<AiBrainIcon width={14} height={14} className="mx-1" />}
      >
        Created by GAIA
      </Chip>
    );
  }
  return null;
}
