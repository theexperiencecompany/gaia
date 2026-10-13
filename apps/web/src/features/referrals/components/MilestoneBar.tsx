import { cn } from "@/lib/utils";
import { REFERRAL_UI_COPY } from "../referralCopy";
import { milestoneWindow } from "../utils/milestones";

interface MilestoneBarProps {
  /** Friends who have paid, which is also free months earned. */
  paidFriends: number;
}

/** One solid bar, split into equal steps by thin ticks, a friend-count marker under each step's end. */
export function MilestoneBar({ paidFriends }: MilestoneBarProps) {
  const { segments, next } = milestoneWindow(paidFriends);
  const progress =
    segments.reduce((sum, segment) => sum + segment.fill, 0) / segments.length;

  return (
    <div className="flex flex-col gap-2.5">
      {paidFriends > 0 && (
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 tabular-nums">
          <p className="text-sm font-medium whitespace-nowrap text-zinc-100">
            {REFERRAL_UI_COPY.monthsEarned(paidFriends)}
          </p>
          <p className="text-[13px] text-zinc-500">
            {REFERRAL_UI_COPY.toNextMilestone(next.remaining, next.milestone)}
          </p>
        </div>
      )}
      <div
        className="relative h-1.5 overflow-hidden rounded-full bg-zinc-700"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={next.milestone}
        aria-valuenow={paidFriends}
        aria-label={REFERRAL_UI_COPY.monthsEarned(paidFriends)}
      >
        <div
          className="absolute inset-y-0 left-0 bg-zinc-100 transition-[width] duration-500 ease-out"
          style={{ width: `${progress * 100}%` }}
        />
        {segments.slice(0, -1).map(({ milestone }, index) => (
          <div
            key={milestone}
            aria-hidden
            className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-zinc-800"
            style={{ left: `${((index + 1) / segments.length) * 100}%` }}
          />
        ))}
      </div>
      <div className="flex">
        {segments.map(({ milestone, fill }) => (
          <span
            key={milestone}
            className={cn(
              "flex-1 text-right text-[11px] tabular-nums",
              fill === 1 ? "text-zinc-300" : "text-zinc-600",
            )}
          >
            {milestone}
          </span>
        ))}
      </div>
    </div>
  );
}
