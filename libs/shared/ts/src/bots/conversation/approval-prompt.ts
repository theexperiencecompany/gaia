/**
 * The chat prompt for approvals the work waits on. A bot has no approve/deny
 * buttons, so the user answers in words and the server's classifier reads the
 * answer; several open approvals are numbered oldest first, as the classifier
 * numbers them, and one already asked is never asked again: a later prompt names
 * only the new ones, under their numbers. Every word of what is asked comes from
 * the server's description; an ask after a yes with a change says the change first,
 * so the user sees it was applied before saying yes again.
 */

import type { ScreenItem } from "../../conversation/types";

type ApprovalRequestedEntry = Extract<
  ScreenItem,
  { kind: "work" }
>["asking"][number];

const MS_PER_MINUTE = 60_000;

/** Every fixed string of the bot approval prompt, in one place. */
const APPROVAL_PROMPT_COPY = {
  single: (action: string) => `**GAIA wants to ${action}**`,
  updated: (changes: string, confirm: string) =>
    `**Updated ${changes}. OK to ${confirm}?**`,
  updatedLine: (changes: string) => `(updated ${changes})`,
  singleReply: (confirm: string) =>
    `Reply **yes** to ${confirm}, or **no** to cancel.`,
  several: (count: number) => `**${count} things need your OK:**`,
  severalReply:
    'Reply **yes** to all, **no** to all, or pick some: "yes 1 and 3".',
  more: (count: number) =>
    count === 1
      ? "**One more needs your OK:**"
      : `**${count} more need your OK:**`,
  moreReply: (number: number) =>
    `Reply by number: "yes ${number}" or "no ${number}".`,
  expires: (within: string) => `This expires in ${within}.`,
} as const;

/** The approval window is hours, so "360 minutes" is not a usable way to say it. */
function formatExpiry(ms: number): string {
  const minutes = Math.max(1, Math.round(ms / MS_PER_MINUTE));
  if (minutes < 60) return minutes === 1 ? "1 minute" : `${minutes} minutes`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? "1 hour" : `${hours} hours`;
}

/** Lower-case the first letter so the action reads inside a sentence ("send an email"). */
function inSentence(action: string): string {
  return action.charAt(0).toLowerCase() + action.slice(1);
}

/** What a yes with a change changed, as words: "priority to high and due date to Friday". */
function changedWords(approval: ApprovalRequestedEntry): string | null {
  const { changes } = approval.description;
  if (changes.length === 0) return null;
  return changes
    .map(({ label, value }) => `${inSentence(label)} to ${value}`)
    .join(" and ");
}

function singlePrompt(approval: ApprovalRequestedEntry, now: number): string {
  const { action, confirm, details } = approval.description;
  const changed = changedWords(approval);
  const facts = [
    changed
      ? APPROVAL_PROMPT_COPY.updated(changed, confirm)
      : APPROVAL_PROMPT_COPY.single(inSentence(action)),
    ...details.map(({ label, value }) => `${label}: ${value}`),
  ];
  const expiry = approval.expires_at
    ? [
        APPROVAL_PROMPT_COPY.expires(
          formatExpiry(Date.parse(approval.expires_at) - now),
        ),
      ]
    : [];
  return [
    facts.join("\n"),
    ...expiry,
    APPROVAL_PROMPT_COPY.singleReply(confirm),
  ].join("\n\n");
}

/** Each approval's line under its number among every open approval. */
function numbered(
  open: readonly ApprovalRequestedEntry[],
  named: readonly ApprovalRequestedEntry[],
): { lines: string; first: number } {
  const numbers = named.map((approval) => open.indexOf(approval) + 1);
  const lines = named
    .map((approval, at) => {
      const changed = changedWords(approval);
      const line = `${numbers[at]}. ${approval.description.headline}`;
      return changed
        ? `${line} ${APPROVAL_PROMPT_COPY.updatedLine(changed)}`
        : line;
    })
    .join("\n");
  return { lines, first: numbers[0] };
}

function severalPrompt(open: readonly ApprovalRequestedEntry[]): string {
  return [
    `${APPROVAL_PROMPT_COPY.several(open.length)}\n${numbered(open, open).lines}`,
    APPROVAL_PROMPT_COPY.severalReply,
  ].join("\n\n");
}

function morePrompt(
  open: readonly ApprovalRequestedEntry[],
  fresh: readonly ApprovalRequestedEntry[],
): string {
  const { lines, first } = numbered(open, fresh);
  return [
    `${APPROVAL_PROMPT_COPY.more(fresh.length)}\n${lines}`,
    APPROVAL_PROMPT_COPY.moreReply(first),
  ].join("\n\n");
}

/**
 * Markdown asking about the fresh approvals among every open one, oldest first;
 * now is the clock the expiry counts from.
 */
export function formatApprovalPrompt(
  open: readonly ApprovalRequestedEntry[],
  fresh: readonly ApprovalRequestedEntry[],
  now: number,
): string {
  if (fresh.length < open.length) return morePrompt(open, fresh);
  return open.length === 1 ? singlePrompt(open[0], now) : severalPrompt(open);
}
