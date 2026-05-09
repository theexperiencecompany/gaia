import type React from "react";
import { cn } from "@/lib/utils";

export type ToolBannerTone =
  | "info"
  | "success"
  | "warning"
  | "danger"
  | "neutral";

const TONE: Record<
  ToolBannerTone,
  { bg: string; title: string; body: string }
> = {
  info: {
    bg: "bg-blue-500/15",
    title: "text-blue-400",
    body: "text-blue-300",
  },
  success: {
    bg: "bg-emerald-500/15",
    title: "text-emerald-400",
    body: "text-emerald-300",
  },
  warning: {
    bg: "bg-amber-500/15",
    title: "text-amber-400",
    body: "text-amber-300",
  },
  danger: {
    bg: "bg-red-500/15",
    title: "text-red-400",
    body: "text-red-300",
  },
  neutral: {
    bg: "bg-zinc-800",
    title: "text-zinc-100",
    body: "text-zinc-400",
  },
};

export interface ToolBannerProps {
  tone?: ToolBannerTone;
  title?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}

export function ToolBanner({
  tone = "info",
  title,
  icon,
  className,
  children,
}: ToolBannerProps) {
  const t = TONE[tone];
  return (
    <div className={cn("rounded-2xl p-3 w-full", t.bg, className)}>
      <div className="flex items-start gap-2">
        {icon && <div className={cn("shrink-0 mt-0.5", t.title)}>{icon}</div>}
        <div className="flex-1 min-w-0">
          {title && (
            <p className={cn("text-sm font-medium", t.title)}>{title}</p>
          )}
          {children && (
            <div className={cn("text-xs", title ? "mt-1" : "", t.body)}>
              {children}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
