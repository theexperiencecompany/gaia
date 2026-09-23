"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface SidebarHeaderButtonProps {
  children: ReactNode;
  tooltip?: ReactNode;
  "aria-label": string;
  className?: string;
  onClick?: () => void;
  onMouseEnter?: () => void;
  onFocus?: () => void;
}

// Lives in its own module, not HeaderManager: HeaderManager imports every
// concrete header, and those headers use this button — exporting it from
// HeaderManager would form an import cycle.
export const SidebarHeaderButton = ({
  children,
  onClick,
  onMouseEnter,
  onFocus,
  tooltip,
  "aria-label": ariaLabel,
  className,
}: SidebarHeaderButtonProps) => {
  const button = (
    <Button
      aria-label={ariaLabel}
      isIconOnly
      radius="md"
      variant="light"
      className={cn("group/btn group h-9 w-9 hover:text-primary", className)}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      onFocus={onFocus}
    >
      {children}
    </Button>
  );

  if (!tooltip) return button;

  return <Tooltip content={tooltip}>{button}</Tooltip>;
};
