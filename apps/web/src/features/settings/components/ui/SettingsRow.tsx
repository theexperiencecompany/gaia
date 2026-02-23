import type { ReactNode } from "react";
import { cn } from "@/lib";

interface SettingsRowProps {
  label: string;
  description?: string;
  children?: ReactNode;
  onClick?: () => void;
  stacked?: boolean;
  className?: string;
  variant?: "default" | "danger";
  /** Optional icon rendered to the left of the label */
  icon?: ReactNode;
}

export function SettingsRow({
  label,
  description,
  children,
  onClick,
  stacked = false,
  className = "",
  variant = "default",
  icon,
}: SettingsRowProps) {
  const labelColor = variant === "danger" ? "text-red-400" : "text-white";

  const inner = (
    <>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {icon && <div className="shrink-0">{icon}</div>}
        <div className="min-w-0 flex-1">
          <p className={cn("text-sm", labelColor)}>{label}</p>
          {description && (
            <p className="mt-0.5 text-xs text-zinc-500">{description}</p>
          )}
        </div>
      </div>
      {children && (
        <div className={cn("ml-4 shrink-0", stacked && "ml-0 mt-2 w-full")}>
          {children}
        </div>
      )}
    </>
  );

  const base = cn(
    "flex px-4 py-3.5",
    stacked ? "flex-col" : "items-center justify-between",
    onClick &&
      "cursor-pointer transition-colors hover:bg-zinc-800/60 active:bg-zinc-800",
    className,
  );

  if (onClick) {
    return (
      <button
        type="button"
        className={cn(base, "w-full text-left")}
        onClick={onClick}
      >
        {inner}
      </button>
    );
  }

  return <div className={base}>{inner}</div>;
}
