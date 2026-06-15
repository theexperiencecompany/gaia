// Goal → emoji mapping for the milestone ladder. The first reward is the gift,
// then the ramp escalates (rocket → crown → gem) and repeats for the endless
// ladder beyond the fourth milestone.
const LADDER_EMOJI = ["🎁", "🚀", "👑", "💎"] as const;

export function emojiForMilestone(index: number): string {
  return LADDER_EMOJI[index % LADDER_EMOJI.length];
}

// Pluralizes the reward into a ticket value/caption pair.
export function ticketCopyForMonths(months: number): {
  value: string;
  caption: string;
} {
  return {
    value: months === 1 ? "1 Month" : `${months} Months`,
    caption: "of GAIA PRO, free",
  };
}
