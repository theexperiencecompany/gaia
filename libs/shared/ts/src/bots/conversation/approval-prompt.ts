/**
 * The chat prompt for approvals the work waits on. A bot has no approve/deny
 * buttons, so the user answers in words and the server's classifier reads the
 * answer; several open approvals are numbered oldest first, as the classifier
 * numbers them.
 */

import type { Entry } from "../../conversation/types";

type ApprovalRequestedEntry = Extract<Entry, { kind: "approval_requested" }>;

const MS_PER_MINUTE = 60_000;

/** The approval window is hours, so "360 minutes" is not a usable way to say it. */
function formatExpiry(ms: number): string {
  const minutes = Math.max(1, Math.round(ms / MS_PER_MINUTE));
  if (minutes < 60) return minutes === 1 ? "1 minute" : `${minutes} minutes`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? "1 hour" : `${hours} hours`;
}

/** Markdown asking about every open approval, oldest first; now is the clock the expiry counts from. */
export function formatApprovalPrompt(
  open: readonly ApprovalRequestedEntry[],
  now: number,
): string {
  if (open.length === 1) {
    const [only] = open;
    const expiry = only.expires_at
      ? ` This expires in ${formatExpiry(Date.parse(only.expires_at) - now)}.`
      : "";
    return (
      `**Approval needed:** ${only.summary}\n` +
      `Reply **yes** to approve or **no** to decline.${expiry}`
    );
  }
  const numbered = open
    .map((approval, index) => `${index + 1}. ${approval.summary}`)
    .join("\n");
  return (
    `**Approvals needed:**\n${numbered}\n` +
    "Reply **yes** to approve all, **no** to decline all, or say which numbers you mean."
  );
}
