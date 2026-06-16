// Realistic mock data for the /dev/referrals GAIA Native page.
// No backend calls. The page reads from this single source of truth.

export const INVITE_PATH = "heygaia.io/invite/aryan";
export const INVITE_URL = `https://${INVITE_PATH}`;

//  Points & goal
// Point weights match the real backend: an activation (a friend signing up and
// becoming active) is +10, a friend subscribing to PRO is +100, and their first
// renewal is +50.
// 140 = (4 activations x 10) + (1 subscription x 100) = 40 + 100. The first
// 100-pt milestone is cleared (1 free month earned); the next is 300.
export const POINTS_PER_ACTIVATION = 10;
export const POINTS_PER_SUBSCRIPTION = 100;
export const POINTS_PER_RENEWAL = 50;
export const POINTS_EARNED = 140;
export const POINTS_GOAL = 300;

//  The offer (shown to the referrer about what their friend gets)
export const FRIEND_OFFER_VALUE = "$30";

export const SHARE_MESSAGE =
  "I've been using GAIA, a proactive personal AI assistant. Here's 50% off your first 2 months of Pro:";

//  Headline stats (Invited / Joined / Upgraded / Months earned)
export const STATS = {
  invited: 7,
  joined: 4,
  upgraded: 1,
  monthsEarned: 1,
} as const;

//  Milestone ladder
// Each tier adds free months on top of the previous, so the cumulative total
// you'll hold at each tier is 1, 3, 6, then 12 months.
//   100 pts: +1 month  (1 total)
//   300 pts: +2 months (3 total)
//   600 pts: +3 months (6 total)
//  1000 pts: +6 months (12 total)
export interface Milestone {
  id: string;
  emoji: string;
  points: number;
  /** Free months this tier adds on its own. */
  monthsAdded: number;
  /** Total free months held once this tier is reached. */
  monthsTotal: number;
  /** Short label for the tier. */
  label: string;
}

export const MILESTONES: Milestone[] = [
  {
    id: "gift",
    emoji: "🎁",
    points: 100,
    monthsAdded: 1,
    monthsTotal: 1,
    label: "First reward",
  },
  {
    id: "rocket",
    emoji: "🚀",
    points: 300,
    monthsAdded: 2,
    monthsTotal: 3,
    label: "Picking up speed",
  },
  {
    id: "crown",
    emoji: "👑",
    points: 600,
    monthsAdded: 3,
    monthsTotal: 6,
    label: "On a roll",
  },
  {
    id: "diamond",
    emoji: "💎",
    points: 1000,
    monthsAdded: 6,
    monthsTotal: 12,
    label: "Legend",
  },
];

// Referred-friends list
export type FriendStatus = "upgraded" | "joined" | "invited";

export interface Friend {
  name: string;
  email: string;
  status: FriendStatus;
  /** Relative time since the latest activity. */
  when: string;
  /** Points this friend has contributed so far. */
  points: number;
}

export const FRIENDS: Friend[] = [
  {
    name: "Maya Chen",
    email: "maya.chen@gmail.com",
    status: "upgraded",
    when: "2 days ago",
    points: POINTS_PER_ACTIVATION + POINTS_PER_SUBSCRIPTION,
  },
  {
    name: "Dev Patel",
    email: "dev.patel@outlook.com",
    status: "joined",
    when: "5 days ago",
    points: POINTS_PER_ACTIVATION,
  },
  {
    name: "Lena Ortiz",
    email: "lena.ortiz@gmail.com",
    status: "joined",
    when: "1 week ago",
    points: POINTS_PER_ACTIVATION,
  },
  {
    name: "Sam Wu",
    email: "sam.wu@hey.com",
    status: "joined",
    when: "1 week ago",
    points: POINTS_PER_ACTIVATION,
  },
  {
    name: "Theo Marsh",
    email: "theo.marsh@gmail.com",
    status: "invited",
    when: "3 days ago",
    points: 0,
  },
];

export const FRIEND_STATUS_LABEL: Record<FriendStatus, string> = {
  upgraded: "Upgraded",
  joined: "Joined",
  invited: "Invited",
};

//  Earned rewards (free months already credited)
export type RewardState = "redeemable" | "applied";

export interface EarnedReward {
  id: string;
  label: string;
  /** "GAIA-FREE-MAR" style code, or null when auto-applied. */
  code: string | null;
  state: RewardState;
  /** Human note on how it's redeemed. */
  note: string;
}

export const EARNED_REWARDS: EarnedReward[] = [
  {
    id: "r1",
    label: "1 month of Pro, free",
    code: "GAIA-FREE-J7K2",
    state: "redeemable",
    note: "Apply this code at checkout or in Billing.",
  },
  {
    id: "r2",
    label: "1 month of Pro, free",
    code: null,
    state: "applied",
    note: "Already applied to your next bill (Jul 1).",
  },
];

//  How it works (numbered stepper)
export const HOW_IT_WORKS: { title: string; body: string }[] = [
  {
    title: "Share your invite link",
    body: "Send it to friends over WhatsApp, X, email, or anywhere else.",
  },
  {
    title: "Your friend gets 50% off Pro and subscribes",
    body: `They save 50% on their first 2 months, a ${FRIEND_OFFER_VALUE} gift.`,
  },
  {
    title: "You earn a free month of Pro",
    body: "Keep inviting to stack months and climb the reward ladder.",
  },
];

//  Derived helpers
export const isUnlocked = (milestone: Milestone): boolean =>
  POINTS_EARNED >= milestone.points;

/** First milestone not yet reached; the one that "breathes". */
export const nextMilestone = (): Milestone | undefined =>
  MILESTONES.find((milestone) => POINTS_EARNED < milestone.points);

export const progressPct = (): number =>
  Math.min(100, Math.round((POINTS_EARNED / POINTS_GOAL) * 100));

/** Horizontal center (0..100) of milestone column `index` when the ladder is
 *  drawn as N evenly-spaced columns. The track node, sticker, and labels all
 *  share this axis, so a column reads as one plumb vertical stack. */
export const columnCenterPct = (index: number, count: number): number =>
  ((index + 0.5) / count) * 100;

/** Map a point total onto the even-column axis by interpolating between the two
 *  surrounding milestone centers, so "you are here" lands proportionally
 *  between the relevant stickers (not on a raw linear point scale). */
export const pointsToLadderPct = (points: number): number => {
  const count = MILESTONES.length;
  const firstCenter = columnCenterPct(0, count);
  const lastCenter = columnCenterPct(count - 1, count);

  if (points <= MILESTONES[0].points) {
    // Ramp from the rail start up to the first node as the first reward nears.
    const frac = Math.max(0, points / MILESTONES[0].points);
    return frac * firstCenter;
  }
  if (points >= MILESTONES[count - 1].points) return lastCenter;

  for (let i = 0; i < count - 1; i++) {
    const lo = MILESTONES[i];
    const hi = MILESTONES[i + 1];
    if (points >= lo.points && points <= hi.points) {
      const frac = (points - lo.points) / (hi.points - lo.points);
      const loCenter = columnCenterPct(i, count);
      const hiCenter = columnCenterPct(i + 1, count);
      return loCenter + frac * (hiCenter - loCenter);
    }
  }
  return lastCenter;
};

/** How far the fill reaches across the even-column ladder axis. */
export const ladderFillPct = (): number => pointsToLadderPct(POINTS_EARNED);

export const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const parseEmails = (raw: string): string[] =>
  raw
    .split(/[\s,;]+/)
    .map((e) => e.trim())
    .filter((e) => EMAIL_PATTERN.test(e));

export const buildWhatsAppUrl = (url: string = INVITE_URL): string =>
  `https://wa.me/?text=${encodeURIComponent(`${SHARE_MESSAGE} ${url}`)}`;

export const buildXUrl = (url: string = INVITE_URL): string =>
  `https://twitter.com/intent/tweet?text=${encodeURIComponent(
    SHARE_MESSAGE,
  )}&url=${encodeURIComponent(url)}`;

export const buildMailUrl = (url: string = INVITE_URL): string =>
  `mailto:?subject=${encodeURIComponent(
    "Try GAIA with me",
  )}&body=${encodeURIComponent(`${SHARE_MESSAGE}\n\n${url}`)}`;
