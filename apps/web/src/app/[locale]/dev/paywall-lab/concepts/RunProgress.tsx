import { Progress } from "@heroui/progress";

interface RunProgressProps {
  label: string;
  /** What is being read right now, cycled as the run advances. */
  items: string[];
  total: number;
  unit: string;
  progress: number;
}

/** The live run: a real count climbing and the item being read, so the work is visible. */
export function RunProgress({
  label,
  items,
  total,
  unit,
  progress,
}: RunProgressProps) {
  const done = Math.round(progress * total);
  const current =
    items[Math.min(Math.floor(progress * items.length), items.length - 1)];
  return (
    <div className="flex flex-1 flex-col justify-center gap-4">
      <p className="text-base font-medium text-zinc-200">{label}</p>
      <Progress
        aria-label={label}
        size="sm"
        value={progress * 100}
        disableAnimation
      />
      <div className="flex items-baseline justify-between gap-4 text-[13px] text-zinc-500">
        <span className="truncate">{current}</span>
        <span className="shrink-0 tabular-nums">
          {done} of {total} {unit}
        </span>
      </div>
    </div>
  );
}
