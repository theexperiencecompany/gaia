"use client";

import { Chip, CloseButton } from "@heroui/react";
import type { ReactNode } from "react";
import { shapeVariants } from "@/components/shared/shape";

interface MentionChipProps {
  name: string;
  icon?: ReactNode;
  onClose?: () => void;
}

/** Inline `@tool` mention pill used in the instructions editor and preview. */
export const MentionChip = ({ name, icon, onClose }: MentionChipProps) => (
  <Chip size="sm" variant="soft" className={shapeVariants({ shape: "pill" })}>
    {icon ? (
      <span className="mr-1 ml-0.5 inline-flex shrink-0 items-center">
        {icon}
      </span>
    ) : undefined}
    {name}
    {onClose ? (
      <CloseButton aria-label={`Remove ${name}`} onPress={onClose} />
    ) : undefined}
  </Chip>
);
