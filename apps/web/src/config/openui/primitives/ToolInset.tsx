import type React from "react";
import { cn } from "@/lib/utils";

export interface ToolInsetProps {
  className?: string;
  /** Drop the inner padding when the child is its own padded surface. */
  flush?: boolean;
  children?: React.ReactNode;
}

/**
 * Nested sub-block for use inside a ToolCard. Renders an additive overlay
 * (bg-white/[0.04]) so it works at any nesting depth without committing to
 * a specific zinc shade. Use for code blocks, diffs, embedded maps,
 * scrollable inner regions.
 *
 * Hard rule: never bg-zinc-900. The white/4 overlay is the only inner tone.
 */
export function ToolInset({ className, flush, children }: ToolInsetProps) {
  return (
    <div
      className={cn(
        "rounded-2xl bg-white/[0.04] overflow-hidden",
        flush ? "" : "p-3",
        className,
      )}
    >
      {children}
    </div>
  );
}
