import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  label: string;
  /** Green when the thing it labels works, zinc when it is off. */
  active: boolean;
}

export function StatusBadge({ label, active }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        active
          ? "bg-emerald-400/10 text-emerald-400"
          : "bg-zinc-700/50 text-zinc-400",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          active ? "bg-emerald-400" : "bg-zinc-500",
        )}
      />
      {label}
    </span>
  );
}
