"use client";

import { Tooltip } from "@heroui/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SidebarHeaderButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
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
  className,
  ...rest
}: SidebarHeaderButtonProps) => {
  const button = (
    <Button
      aria-label={ariaLabel}
      size="icon"
      variant="ghost"
      className={cn(
        "group/btn group rounded-xl p-1! hover:bg-primary/20 hover:text-primary",
        className,
      )}
      onClick={onClick}
      {...rest}
    >
      {children}
    </Button>
  );

  if (!tooltip) return button;

  return <Tooltip content={tooltip}>{button}</Tooltip>;
};
