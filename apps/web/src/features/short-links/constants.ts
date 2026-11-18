import type {
  LinkAccess,
  LinkDenial,
  ReportReason,
} from "@/types/features/shortLinkTypes";

import { LINK_CONSTANTS } from "./link-constants.generated";

interface AccessOption {
  label: string;
  description: string;
  /** Who can open a link at this level, completing "Anyone with ... can view it". */
  copiedNote: string;
}

export const LINK_ACCESS_OPTIONS: Record<LinkAccess, AccessOption> = {
  public: {
    label: "Public",
    description: "Anyone, and search engines",
    copiedNote: "Anyone can view it, and search engines may list it.",
  },
  unlisted: {
    label: "Anyone with the link",
    description: "Never listed by search engines",
    copiedNote: "Anyone with this link can view it.",
  },
  people: {
    label: "Specific people",
    description: "Signed-in GAIA users with an email you add",
    copiedNote: "Only the people you added can view it, once signed in.",
  },
  owner: {
    label: "Only you",
    description: "Nobody else can open it",
    copiedNote: "Only you can open it.",
  },
};

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

/** The denials a signed-in viewer might get past, so the browser resolves them again. */
export const GATED_LINK_DENIALS = [
  "link_sign_in_required",
  "link_forbidden",
] as const satisfies readonly LinkDenial[];

/**
 * Every denial the server's anonymous resolve hands to the viewer's browser: the
 * gated ones, and the dead ones the link's owner still opens.
 */
export const BROWSER_RESOLVED_DENIALS: ReadonlySet<string> = new Set([
  ...GATED_LINK_DENIALS,
  ...LINK_CONSTANTS.ownerStillOpens,
]);

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
