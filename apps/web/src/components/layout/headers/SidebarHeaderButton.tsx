"use client";

import { Tooltip } from "@heroui/react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SidebarHeaderButtonProps
  extends React.HTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  tooltip?: ReactNode;
  "aria-label": string;
}

export const SidebarHeaderButton = ({
  children,
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
      {...rest}
      className={cn(
        "group/btn group rounded-xl p-1! hover:bg-primary/20 hover:text-primary",
        className,
      )}
    >
      {children}
    </Button>
  );

  if (!tooltip) return button;

  return <Tooltip content={tooltip}>{button}</Tooltip>;
};
