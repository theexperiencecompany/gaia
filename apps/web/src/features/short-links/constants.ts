import type { LinkAccess, ReportReason } from "@/types/features/shortLinkTypes";

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

/**
 * User-agent markers of the bots that fetch a link to build a chat preview, and
 * the crawlers that run a page's script. Matched case-insensitively. Mirrors
 * UNFURL_BOT_USER_AGENT_MARKERS in apps/api/app/constants/short_links.py.
 */
export const UNFURL_BOT_USER_AGENT_MARKERS = [
  "slackbot",
  "facebookexternalhit",
  "facebot",
  "whatsapp/",
  "telegrambot",
  "twitterbot",
  "discordbot",
  "linkedinbot",
  "googlebot",
  "bingbot",
  "applebot",
] as const;

/** What a dead link says, keyed by the API's denial code. No owner, title or type is ever disclosed. */
export const DEAD_LINK_COPY = {
  link_not_found: "This link doesn't exist.",
  link_revoked:
    "This link was turned off by the person who shared it. Ask them for a new one.",
  link_expired:
    "This link has expired. Ask the person who shared it for a new one.",
  link_target_deleted: "What this link pointed to was deleted.",
  link_removed: "This link was removed for breaking GAIA's terms.",
} as const;

export const SIGN_IN_REQUIRED_COPY = "Sign in to open this";
export const FORBIDDEN_COPY = "You don't have access to this.";

export const LINK_DENIAL_CODES = {
  signInRequired: "link_sign_in_required",
  forbidden: "link_forbidden",
} as const;

/**
 * The sandbox an active (HTML) snapshot runs in: scripts and forms but no
 * same-origin (so no storage or cookies) and no top navigation (so it cannot
 * redirect the viewer's tab). The content origin's CSP repeats it.
 */
export const ACTIVE_CONTENT_SANDBOX =
  "allow-scripts allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads";

/** Fetch a fresh content URL this long before the current one expires. */
export const CONTENT_URL_REFRESH_MARGIN_MS = 30_000;

export const REPORT_REASON_LABELS: Record<ReportReason, string> = {
  phishing: "Phishing or a scam",
  malware: "Malware or a harmful download",
  harassment: "Harassment or hate",
  illegal: "Illegal content",
  other: "Something else",
};

export const REPORT_COPY = {
  sent: "Thanks. We'll review this link.",
  failed: "Couldn't send the report",
  verificationFailed:
    "We could not verify that you are human. Reload the page and try again.",
} as const;
