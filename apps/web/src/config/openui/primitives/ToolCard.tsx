import type React from "react";
import { cn } from "@/lib/utils";

export type ToolCardSize = "compact" | "standard" | "wide" | "full";

const SIZE_MAX_W: Record<ToolCardSize, string> = {
  compact: "max-w-md",
  standard: "max-w-2xl",
  wide: "max-w-4xl",
  full: "",
};

export interface ToolCardProps {
  size?: ToolCardSize;
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}

export function ToolCard({
  size = "standard",
  title,
  subtitle,
  footer,
  className,
  children,
}: ToolCardProps) {
  const hasHeader = title != null || subtitle != null;
  return (
    <div
      className={cn(
        "rounded-2xl bg-zinc-800 p-4 w-full",
        SIZE_MAX_W[size],
        className,
      )}
    >
      {hasHeader && (
        <div className="mb-3">
          {title && (
            <p className="text-sm font-semibold text-zinc-100">{title}</p>
          )}
          {subtitle && (
            <p className="text-xs text-zinc-400 mt-0.5">{subtitle}</p>
          )}
        </div>
      )}
      <div className="flex flex-col gap-3">{children}</div>
      {footer && <div className="mt-3">{footer}</div>}
    </div>
  );
}
