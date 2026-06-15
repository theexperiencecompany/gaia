"use client";

import { Progress } from "@heroui/progress";

import type { MilestoneState, ReferralOverview } from "../types";
import { AppleEmojiSticker } from "./AppleEmojiSticker";
import { emojiForMilestone } from "./referralVisuals";

function LadderStep({
  milestone,
  index,
}: {
  milestone: MilestoneState;
  index: number;
}) {
  const isNext = milestone.status === "next";
  const isLocked = milestone.status === "locked";

  return (
    <div className="flex w-16 shrink-0 flex-col items-center gap-2">
      <AppleEmojiSticker
        emoji={emojiForMilestone(index)}
        size={44}
        dimmed={isLocked}
        pulse={isNext}
      />
      <span
        className={`text-xs font-medium tabular-nums ${
          isNext ? "text-primary" : isLocked ? "text-zinc-600" : "text-zinc-300"
        }`}
      >
        {milestone.threshold}
      </span>
    </div>
  );
}

export function GoalLadder({ overview }: { overview: ReferralOverview }) {
  const friendsToGo = Math.max(
    0,
    overview.next_goal_threshold - overview.points,
  );
  const friendsLabel = friendsToGo === 1 ? "friend" : "friends";
  // Size of the current goal segment: points already in it + points still to go.
  const segmentSize = overview.points_into_current_goal + friendsToGo;

  return (
    <div className="space-y-5">
      <div className="no-scrollbar overflow-x-auto">
        <div className="flex items-start gap-2 px-1 pb-1">
          {overview.ladder.map((milestone, index) => (
            <LadderStep
              key={milestone.threshold}
              milestone={milestone}
              index={index}
            />
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Progress
          aria-label="Progress to your next free month"
          color="primary"
          size="sm"
          value={overview.progress_pct}
          classNames={{ track: "bg-zinc-800" }}
        />
        <div className="flex items-center justify-between">
          <p className="text-sm text-zinc-400">
            {friendsToGo === 0
              ? "You've reached your next free month."
              : `${friendsToGo} ${friendsLabel} to your next free month.`}
          </p>
          <span className="text-xs tabular-nums text-zinc-600">
            {overview.points_into_current_goal}/{segmentSize}
          </span>
        </div>
      </div>
    </div>
  );
}
