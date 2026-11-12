import type { ReportReason } from "@/types/features/shortLinkTypes";

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
