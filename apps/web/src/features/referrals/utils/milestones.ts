/**
 * Friend-count markers for the progress bar. They are signposts only: every
 * paying friend is exactly one free month, at 3 friends or at 300.
 */
const FIRST_MILESTONES = [1, 3, 5];
/** From 10 on, markers follow 1-2.5-5 steps (10, 25, 50, 100, 250...), so there is always a next one. */
const NICE_STEPS = [1, 2.5, 5];
const FIRST_NICE_DECADE = 10;
/** How many markers the bar shows at once. */
const VISIBLE_MILESTONES = 5;

function milestoneAt(index: number): number {
  if (index < FIRST_MILESTONES.length) return FIRST_MILESTONES[index];
  const nice = index - FIRST_MILESTONES.length;
  const decade = FIRST_NICE_DECADE * 10 ** Math.floor(nice / NICE_STEPS.length);
  return decade * NICE_STEPS[nice % NICE_STEPS.length];
}

export interface MilestoneSegment {
  /** The marker this segment ends on. */
  milestone: number;
  /** 0 to 1: how much of the way from the previous marker the count has come. */
  fill: number;
}

export interface MilestoneWindow {
  segments: MilestoneSegment[];
  /** The first marker still ahead, and how many friends until it. */
  next: { milestone: number; remaining: number };
}

/** The five markers around a count, sliding forward once it passes the last one. */
export function milestoneWindow(count: number): MilestoneWindow {
  let nextIndex = 0;
  while (milestoneAt(nextIndex) <= count) nextIndex += 1;
  const lastIndex = Math.max(nextIndex, VISIBLE_MILESTONES - 1);
  const firstIndex = lastIndex - (VISIBLE_MILESTONES - 1);

  const segments: MilestoneSegment[] = [];
  for (let index = firstIndex; index <= lastIndex; index += 1) {
    const start = index === 0 ? 0 : milestoneAt(index - 1);
    const end = milestoneAt(index);
    segments.push({
      milestone: end,
      fill: Math.min(1, Math.max(0, (count - start) / (end - start))),
    });
  }

  const nextMilestone = milestoneAt(nextIndex);
  return {
    segments,
    next: { milestone: nextMilestone, remaining: nextMilestone - count },
  };
}
