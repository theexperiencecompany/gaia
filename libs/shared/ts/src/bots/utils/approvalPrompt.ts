/**
 * The yes/no question a bot sends for pending approvals, one formatter for every
 * platform (each adapter's markdown conversion renders it). Bots have no buttons,
 * so the user answers in chat and the server's reply classifier decides.
 */
import type { ApprovalRequestData } from "../../chat";
import {
  approvalAgeSeconds,
  approvalExpiresAt,
  cardDescription,
  formatApprovalAge,
} from "../../chat/approvals";

/** Every fixed string of the bot approval prompt, in one place. */
export const APPROVAL_PROMPT_COPY = {
  single: (action: string) => `GAIA wants to ${action}`,
  singleReply: (confirm: string) => `Reply yes to ${confirm}, or no to cancel.`,
  several: (count: number) => `${count} things need your OK:`,
  severalReply: 'Reply yes to all, no to all, or pick some: "yes 1 and 3".',
  asked: (age: string) => `Asked ${age}.`,
  expires: (within: string) =>
    `If you don't answer, this expires in ${within}.`,
} as const;

/** Lower-case the first letter so the action reads inside a sentence ("send an email"). */
function inSentence(action: string): string {
  return action.charAt(0).toLowerCase() + action.slice(1);
}

/** A stale card says how old it is, so a late "yes" is a deliberate one. */
function ageLine(card: ApprovalRequestData, now: number): string | null {
  const age = approvalAgeSeconds(card, now);
  return age !== null && age >= 60
    ? APPROVAL_PROMPT_COPY.asked(formatApprovalAge(age))
    : null;
}

/** Only an approval that really expires says so; ledger approvals never do. */
function expiryLine(card: ApprovalRequestData, now: number): string | null {
  const expiresAt = approvalExpiresAt(card);
  const until = expiresAt === null ? Number.NaN : Date.parse(expiresAt) - now;
  if (Number.isNaN(until) || until <= 0) return null;
  const minutes = Math.max(1, Math.round(until / 60000));
  const hours = Math.round(minutes / 60);
  return APPROVAL_PROMPT_COPY.expires(
    minutes < 60
      ? `${minutes} min`
      : `${hours} ${hours === 1 ? "hour" : "hours"}`,
  );
}

function singlePrompt(card: ApprovalRequestData, now: number): string {
  const description = cardDescription(card);
  const lines = [APPROVAL_PROMPT_COPY.single(inSentence(description.action))];
  for (const detail of description.details) {
    lines.push(`${detail.label}: ${detail.value}`);
  }
  const notes = [ageLine(card, now), expiryLine(card, now)].filter(
    (line): line is string => line !== null,
  );
  return [
    lines.join("\n"),
    ...(notes.length > 0 ? [notes.join(" ")] : []),
    APPROVAL_PROMPT_COPY.singleReply(description.confirm),
  ].join("\n\n");
}

function severalPrompt(cards: ApprovalRequestData[]): string {
  const items = cards.map(
    (card, index) => `${index + 1}. ${cardDescription(card).headline}`,
  );
  return [
    APPROVAL_PROMPT_COPY.several(cards.length),
    items.join("\n"),
    APPROVAL_PROMPT_COPY.severalReply,
  ].join("\n\n");
}

/**
 * One message for every pending approval: the action and its facts for one, a
 * numbered list for several, in the order given (the server's reply order).
 */
export function formatApprovalPrompt(
  cards: ApprovalRequestData[],
  now: number = Date.now(),
): string {
  // Kept in the given order: the server numbers the reply against exactly this list.
  const pending = cards.filter((card) => card.status === "pending");
  if (pending.length === 0) return "";
  return pending.length === 1
    ? singlePrompt(pending[0], now)
    : severalPrompt(pending);
}
