"use client";

import { Chip, type ChipProps } from "@heroui/chip";
import type { ReactNode } from "react";

interface MentionChipProps {
  name: string;
  icon?: ReactNode;
  onClose?: () => void;
  radius?: ChipProps["radius"];
}

/** Inline `@tool` mention pill used in the instructions editor and preview. */
export const MentionChip = ({
  name,
  icon,
  onClose,
  radius = "full",
}: MentionChipProps) => (
  <Chip
    size="sm"
    variant="flat"
    radius={radius}
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
