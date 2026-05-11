import type React from "react";
import { cn } from "@/lib/utils";

export interface ToolGridProps {
  /**
   * Minimum width in pixels each child can shrink to before wrapping.
   * Defaults to 200.
   */
  min?: number;
  className?: string;
  children?: React.ReactNode;
}

/**
 * Auto-wrapping flex grid. Each direct child stretches to fill available
 * row space and wraps to the next line when it would shrink below `min`.
 *
 * Children are bare — no background, no radius. Compose with ToolCard or
 * any visual treatment as desired.
 */
export function ToolGrid({ min = 200, className, children }: ToolGridProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap gap-3 items-stretch",
        "[&>*]:flex-1 [&>*]:min-w-[var(--tool-grid-min)]",
        className,
      )}
      style={
        {
          "--tool-grid-min": `${min}px`,
        } as React.CSSProperties
      }
    >
      {children}
    </div>
  );
}
