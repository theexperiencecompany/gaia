import type React from "react";

interface TodaySectionProps {
  label: string;
  count: number;
  children: React.ReactNode;
}

/** Tracked-caps section label + count, hairline fill, then the row list. */
export const TodaySection: React.FC<TodaySectionProps> = ({
  label,
  count,
  children,
}) => {
  if (count === 0) return null;

  return (
    <section aria-label={label}>
      <div className="flex items-center gap-3 px-3 pb-2">
        <h2 className="text-xs font-semibold text-zinc-400">{label}</h2>
        <span className="text-xs text-zinc-600 tabular-nums">{count}</span>
        <div className="h-px flex-1 bg-zinc-800/70" />
      </div>
      <div className="flex flex-col gap-0.5">{children}</div>
    </section>
  );
};
