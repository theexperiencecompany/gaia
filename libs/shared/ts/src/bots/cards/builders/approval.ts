import {
  approvalOutcomeLabel,
  formatApprovalAge,
  isSettled,
} from "../../../chat/approvals";
import type { ApprovalRequestData } from "../../../chat/approvals.types";
import { flattenArgsPreview } from "../../../utils/argsPreview";
import { type BotActionable, heldActionIds } from "../invoke";
import type {
  Card,
  CardBlock,
  CardField,
  CardInvokeAction,
  CardReplyAction,
  CardStatusTone,
} from "../types";
import { joinMeta } from "./card-parts";

/** An approval as a bot receives it: with its Approve and Deny action ids. */
type BotApproval = ApprovalRequestData & BotActionable<"approve" | "deny">;

/** A value longer than this, or spanning lines, reads as a quote, not a table cell. */
const FIELD_VALUE_MAX = 80;
const REVISE_LABEL = "Suggest changes";
const FEEDBACK_CITE = "Your note";

/** What a text-only platform's user does instead of tapping. */
const DECISION_HINT =
  "Reply **yes** to approve, **no** to decline, or tell me what to change.";

const SECONDS_PER_MINUTE = 60;
const MINUTES_PER_HOUR = 60;

/** The approval window is hours, so "360 minutes" is not a usable way to say it. */
function formatExpiry(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / SECONDS_PER_MINUTE));
  if (minutes < MINUTES_PER_HOUR) {
    return minutes === 1 ? "1 minute" : `${minutes} minutes`;
  }
  const hours = Math.round(minutes / MINUTES_PER_HOUR);
  return hours === 1 ? "1 hour" : `${hours} hours`;
}

const DECISION_BUTTONS = [
  { verb: "approve", label: "Approve", style: "primary" },
  { verb: "deny", label: "Deny", style: "danger" },
] as const;

/** Approve / Deny buttons, each one the API made tappable. */
function decisionActions(data: BotApproval): CardInvokeAction[] {
  return DECISION_BUTTONS.flatMap(({ verb, label, style }) => {
    const actionId = data.bot_actions?.[verb];
    if (!actionId) return [];
    const action: CardInvokeAction = {
      kind: "invoke",
      label,
      actionId,
      objectKey: data.approval_id,
      style,
    };
    return [action];
  });
}

/** "Suggest changes": the answer is a chat reply, which the approval resolver reads as a rejection with that feedback. */
const REVISE_ACTION: CardReplyAction = {
  kind: "reply",
  label: REVISE_LABEL,
  prompt: "revise_approval",
};

/** Rows arrive as "subject"; a label reads "Subject", as on the web card. */
function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function isLongValue(value: string): boolean {
  return value.length > FIELD_VALUE_MAX || value.includes("\n");
}

/**
 * What the call will do, the way the web card shows it: short arguments as a
 * table, long ones (an email body) as collapsible quotes named by their field.
 */
function argumentBlocks(data: BotApproval): CardBlock[] {
  const { rows, omitted } = flattenArgsPreview(data.args_preview);
  const fields: CardField[] = [];
  const quotes: CardBlock[] = [];
  for (const row of rows) {
    const key = capitalize(row.key);
    const label = row.group ? `${row.group} ${key}` : key;
    if (isLongValue(row.value)) {
      quotes.push({
        kind: "quote",
        markdown: row.value,
        collapsible: true,
        cite: label,
      });
    } else {
      fields.push({ label, value: row.value });
    }
  }
  if (omitted > 0) fields.push({ label: "More", value: `${omitted} more` });
  return [
    ...(fields.length > 0 ? [{ kind: "fields" as const, fields }] : []),
    ...quotes,
  ];
}

function pendingFooter(data: BotApproval): string | undefined {
  return joinMeta([
    data.integration_name,
    data.age_seconds != null ? formatApprovalAge(data.age_seconds) : null,
    `expires in ${formatExpiry(data.timeout_seconds)}`,
  ]);
}

function pendingCard(data: BotApproval): Card {
  const decisions = decisionActions(data);
  return {
    title: data.summary,
    accent: "warning",
    status: { label: "Needs approval", tone: "warning" },
    blocks: [
      ...(data.rationale
        ? [{ kind: "text" as const, markdown: `_${data.rationale}_` }]
        : []),
      ...argumentBlocks(data),
    ],
    actions: decisions.length > 0 ? [...decisions, REVISE_ACTION] : [],
    textHint: DECISION_HINT,
    footer: pendingFooter(data),
    actionIds: heldActionIds(data),
  };
}

/** The receipt's badge colour per decided status. */
const SETTLED_TONE: Partial<
  Record<ApprovalRequestData["status"], CardStatusTone>
> = {
  approved: "success",
  auto_approved: "success",
  denied: "danger",
};

/** The receipt's headline per decided status; the detail is the card body. */
const SETTLED_TITLE: Partial<Record<ApprovalRequestData["status"], string>> = {
  approved: "Approved",
  auto_approved: "Approved automatically",
  denied: "Not approved",
  timeout: "Expired",
  abandoned: "Dropped",
  revoked: "Withdrawn",
};

/** A decided approval: the receipt the tapped card turns into, the user's note quoted. */
function settledCard(data: BotApproval): Card {
  const blocks: CardBlock[] = [{ kind: "text", markdown: data.summary }];
  if (data.status === "denied" && data.feedback?.trim()) {
    blocks.push({
      kind: "quote",
      markdown: data.feedback.trim(),
      cite: FEEDBACK_CITE,
    });
  } else {
    blocks.push({ kind: "text", markdown: `_${approvalOutcomeLabel(data)}_` });
  }
  const title = SETTLED_TITLE[data.status] ?? approvalOutcomeLabel(data);
  return {
    title,
    accent: "brand",
    status: { label: title, tone: SETTLED_TONE[data.status] ?? "info" },
    blocks,
    actions: [],
    footer: data.integration_name ?? undefined,
    actionIds: heldActionIds(data),
  };
}

/**
 * The HIL approval prompt: what will run and with what, Approve / Deny, and
 * "Suggest changes" for a rejection that tells the agent what to redo. Once
 * decided, the receipt a tapped card is updated to.
 */
export function buildApprovalCards(data: BotApproval): Card[] {
  return [isSettled(data.status) ? settledCard(data) : pendingCard(data)];
}

/**
 * Only a PENDING approval is posted as a new card: settled ones (auto-approved,
 * or a resumed decision) are re-emitted mid-stream and narrated by the agent's
 * own reply, so posting them would fragment it.
 */
export function isApprovalPosted(data: BotApproval): boolean {
  return !isSettled(data.status);
}
