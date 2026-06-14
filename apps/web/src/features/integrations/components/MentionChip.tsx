"use client";

import { Chip } from "@heroui/chip";
import type { ReactNode } from "react";

interface MentionChipProps {
  name: string;
  icon?: ReactNode;
  onClose?: () => void;
}

/** Inline `@tool` mention pill used in the instructions editor and preview. */
export const MentionChip = ({ name, icon, onClose }: MentionChipProps) => (
  <Chip
    size="sm"
    variant="flat"
    radius="full"
    startContent={
      icon ? (
        <span className="ml-0.5 mr-1 inline-flex shrink-0 items-center">
          {icon}
        </span>
      ) : undefined
    }
    onClose={onClose}
  >
    {name}
  </Chip>
);
