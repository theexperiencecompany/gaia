import type { LinkAccess } from "@/types/features/shortLinkTypes";

/** Mirrors MAX_GRANTEES in apps/api/app/models/short_link_models.py. */
export const MAX_GRANTEES = 50;

interface AccessOption {
  label: string;
  description: string;
  /** Who can open a link at this level, completing "Anyone with ... can view it". */
  copiedNote: string;
  /** Wider levels rank higher; a file narrowed to a level is served at it and below. */
  breadth: number;
}

export const LINK_ACCESS_OPTIONS: Record<LinkAccess, AccessOption> = {
  public: {
    label: "Public",
    description: "Anyone, and search engines",
    copiedNote: "Anyone can view it, and search engines may list it.",
    breadth: 3,
  },
  unlisted: {
    label: "Anyone with the link",
    description: "Never listed by search engines",
    copiedNote: "Anyone with this link can view it.",
    breadth: 2,
  },
  people: {
    label: "Specific people",
    description: "Signed-in GAIA users with an email you add",
    copiedNote: "Only the people you added can view it, once signed in.",
    breadth: 1,
  },
  owner: {
    label: "Only you",
    description: "Nobody else can open it",
    copiedNote: "Only you can open it.",
    breadth: 0,
  },
};

export const LINK_ACCESS_ORDER: LinkAccess[] = [
  "public",
  "unlisted",
  "people",
  "owner",
];

const DAY_MS = 24 * 60 * 60 * 1000;

export const EXPIRY_PRESETS = [
  { key: "1d", label: "1 day", ms: DAY_MS },
  { key: "7d", label: "7 days", ms: 7 * DAY_MS },
  { key: "30d", label: "30 days", ms: 30 * DAY_MS },
] as const;

export type ExpiryChoice =
  | (typeof EXPIRY_PRESETS)[number]["key"]
  | "never"
  | "keep";
