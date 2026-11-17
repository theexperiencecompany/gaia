/**
 * The chat prompt for approvals the work waits on. A bot has no approve/deny
 * buttons, so the user answers in words and the server's classifier reads the
 * answer; several open approvals carry the numbers the server gave them when
 * they were asked, and one already asked is never asked again: a later prompt names
 * only the new ones, under their numbers. Every word of what is asked comes from
 * the server's description: its question for one approval (which leads with the
 * change on an ask after a yes with a change), its headline in a list.
 */

import type { ScreenItem } from "../../conversation/types";

type ApprovalRequestedEntry = Extract<
  ScreenItem,
  { kind: "work" }
>["asking"][number];

/** Every fixed string of the bot approval prompt, in one place. */
const APPROVAL_PROMPT_COPY = {
  question: (question: string) => `**${question}**`,
  singleReply: "Reply **yes** or **no**.",
  updatedLine: (note: string) => `(${note})`,
  several: (count: number) => `**${count} things need your OK:**`,
  severalReply:
    'Reply **yes** to all, **no** to all, or pick some: "yes 1 and 3".',
  more: (count: number) =>
    count === 1
      ? "**One more needs your OK:**"
      : `**${count} more need your OK:**`,
  moreReply: (number: number) =>
    `Reply by number: "yes ${number}" or "no ${number}".`,
} as const;

/** Lower-case the first letter so a note reads inside a sentence ("updated priority"). */
function inSentence(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

function singlePrompt(approval: ApprovalRequestedEntry): string {
  const { headline, question, details, change_note } = approval.description;
  // A re-ask's question already says the change; the rest was asked before.
  const shown = change_note ? [] : details;
  // Entries logged before the server phrased questions carry only a headline.
  const facts = [
    APPROVAL_PROMPT_COPY.question(question ?? headline),
    ...shown.map(({ label, value }) => `${label}: ${value}`),
  ];
  return [facts.join("\n"), APPROVAL_PROMPT_COPY.singleReply].join("\n\n");
}

/**
 * The number the server gave the approval when it was asked, which the reply
 * resolver reads "yes 2" against; a request logged before numbering takes its place.
 */
function numberOf(
  open: readonly ApprovalRequestedEntry[],
  approval: ApprovalRequestedEntry,
): number {
  return approval.number ?? open.indexOf(approval) + 1;
}

/** Each approval's line under its number. */
function numbered(
  open: readonly ApprovalRequestedEntry[],
  named: readonly ApprovalRequestedEntry[],
): { lines: string; first: number } {
  const numbers = named.map((approval) => numberOf(open, approval));
  const lines = named
    .map((approval, at) => {
      const { headline, change_note } = approval.description;
      const line = `${numbers[at]}. ${headline}`;
      return change_note
        ? `${line} ${APPROVAL_PROMPT_COPY.updatedLine(inSentence(change_note))}`
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

/** Markdown asking about the fresh approvals among every open one, oldest first. */
export function formatApprovalPrompt(
  open: readonly ApprovalRequestedEntry[],
  fresh: readonly ApprovalRequestedEntry[],
): string {
  if (fresh.length < open.length) return morePrompt(open, fresh);
  return open.length === 1 ? singlePrompt(open[0]) : severalPrompt(open);
}
