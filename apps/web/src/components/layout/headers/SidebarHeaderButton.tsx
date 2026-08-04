"use client";

import { Tooltip } from "@heroui/react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface SidebarHeaderButtonProps
  extends React.HTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode;
  onClick?: () => void;
  tooltip?: ReactNode;
  "aria-label": string;
}

// Consistent button component for sidebar header buttons.
// Lives in its own module rather than in HeaderManager: HeaderManager imports
// every concrete header, and those headers use this button, so exporting it
// from there formed an import cycle.
export const SidebarHeaderButton = ({
  children,
  onClick,
  tooltip,
  "aria-label": ariaLabel,
  ...rest
}: SidebarHeaderButtonProps) => {
  const button = (
    <Button
      aria-label={ariaLabel}
      size="icon"
      variant="ghost"
      className={`group/btn group rounded-xl p-1! hover:bg-primary/20 hover:text-primary`}
      onClick={onClick}
      {...rest}
    >
      {children}
    </Button>
  );

  if (!tooltip) return button;

  return <Tooltip content={tooltip}>{button}</Tooltip>;
};
