// Shared realistic mock data for the four /dev/referrals share-page directions.
// No backend calls — every surface reads from this single source of truth.

export const REFERRAL_USER = "Aryan";
export const INVITE_PATH = "heygaia.io/invite/aryan";
export const INVITE_URL = `https://${INVITE_PATH}`;
export const INVITE_CODE = "GAIA26";

export const POINTS_EARNED = 110;
export const POINTS_GOAL = 300;

export const STATS = {
  invited: 7,
  joined: 4,
  upgraded: 1,
} as const;

export const SHARE_MESSAGE =
  "I've been using GAIA — a proactive personal AI assistant. Here's 50% off your first 2 months of PRO:";

export interface Milestone {
  id: string;
  emoji: string;
  points: number;
  label: string;
  reward: string;
}

// 🎁 → 🚀 → 👑 → 💎  — unlock as points cross each threshold.
export const MILESTONES: Milestone[] = [
  {
    id: "gift",
    emoji: "🎁",
    points: 50,
    label: "First invite",
    reward: "1 week of PRO",
  },
  {
    id: "rocket",
    emoji: "🚀",
    points: 150,
    label: "Getting going",
    reward: "1 month of PRO",
  },
  {
    id: "crown",
    emoji: "👑",
    points: 300,
    label: "On a roll",
    reward: "3 months of PRO",
  },
  {
    id: "diamond",
    emoji: "💎",
    points: 600,
    label: "Legend",
    reward: "1 year of PRO",
  },
];

export interface Friend {
  name: string;
  handle: string;
  status: "joined" | "upgraded" | "pending";
  points: number;
}

export const FRIENDS: Friend[] = [
  { name: "Maya Chen", handle: "maya", status: "upgraded", points: 50 },
  { name: "Dev Patel", handle: "devp", status: "joined", points: 20 },
  { name: "Lena Ortiz", handle: "lena", status: "joined", points: 20 },
  { name: "Sam Wu", handle: "samwu", status: "joined", points: 20 },
  { name: "Theo Marsh", handle: "theo", status: "pending", points: 0 },
];

export const LEADERBOARD = [
  { rank: 10, name: "priya.k", points: 140 },
  { rank: 11, name: "jordan", points: 120 },
  { rank: 12, name: "You", points: POINTS_EARNED, isYou: true },
  { rank: 13, name: "alex.r", points: 90 },
  { rank: 14, name: "nina", points: 80 },
];

export const isUnlocked = (m: Milestone): boolean => POINTS_EARNED >= m.points;

/** First milestone not yet reached — the one that "breathes". */
export const nextMilestone = (): Milestone | undefined =>
  MILESTONES.find((m) => POINTS_EARNED < m.points);

export const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const buildWhatsAppUrl = (): string =>
  `https://wa.me/?text=${encodeURIComponent(`${SHARE_MESSAGE} ${INVITE_URL}`)}`;

export const buildXUrl = (): string =>
  `https://twitter.com/intent/tweet?text=${encodeURIComponent(
    SHARE_MESSAGE,
  )}&url=${encodeURIComponent(INVITE_URL)}`;

export const buildMailUrl = (): string =>
  `mailto:?subject=${encodeURIComponent(
    "Try GAIA with me",
  )}&body=${encodeURIComponent(`${SHARE_MESSAGE}\n\n${INVITE_URL}`)}`;
