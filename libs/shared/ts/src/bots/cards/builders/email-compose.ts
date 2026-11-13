import type { EmailComposeData } from "../../../chat/types";
import { truncateText } from "../../../utils/formatters";
import { htmlToPlainText } from "../../utils/formatters";
import { type BotActionable, heldActionIds } from "../invoke";
import type { Card, CardBlock, CardField, CardInvokeAction } from "../types";

/** A draft as a bot receives it: with its Send action id. */
type BotEmailDraft = EmailComposeData & BotActionable<"send">;

const DRAFT_TITLE = "Draft ready";
const SENT_TITLE = "Email sent";
/** Enough of the body to recognise the draft; the full text is in Gmail. */
const EMAIL_BODY_PREVIEW_MAX = 600;
const SEND_LABEL = "Send";
/** The card is only shown once the draft exists in Gmail. */
const DRAFT_FOOTER = "Saved to your Gmail drafts";
/** Asking GAIA in chat is how a text-only platform's user sends it. */
const SEND_HINT = "To send it, reply and ask me to.";
const RECIPIENT_SEPARATOR = ", ";
/** Each draft is its own card, so its Send button is the card's only object. */
const DRAFT_OBJECT_KEY = "draft";

function draftFields(draft: BotEmailDraft): CardField[] {
  const fields: CardField[] = [
    { label: "To", value: draft.to.join(RECIPIENT_SEPARATOR) },
  ];
  if (draft.cc && draft.cc.length > 0) {
    fields.push({ label: "Cc", value: draft.cc.join(RECIPIENT_SEPARATOR) });
  }
  fields.push({ label: "Subject", value: draft.subject });
  return fields;
}

function bodyPreview(draft: BotEmailDraft): string {
  const body = draft.is_html ? htmlToPlainText(draft.body) : draft.body;
  return truncateText(body.trim(), EMAIL_BODY_PREVIEW_MAX);
}

function sendActions(draft: BotEmailDraft): CardInvokeAction[] {
  const actionId = draft.bot_actions?.send;
  if (!actionId || draft.sent) return [];
  return [
    {
      kind: "invoke",
      label: SEND_LABEL,
      actionId,
      objectKey: DRAFT_OBJECT_KEY,
      style: "primary",
    },
  ];
}

function buildDraftCard(draft: BotEmailDraft): Card {
  const preview = bodyPreview(draft);
  const blocks: CardBlock[] = [{ kind: "fields", fields: draftFields(draft) }];
  if (preview) {
    blocks.push({ kind: "quote", markdown: preview, collapsible: !draft.sent });
  }
  return {
    title: draft.sent ? SENT_TITLE : DRAFT_TITLE,
    accent: "brand",
    status: draft.sent
      ? { label: "Sent", tone: "success" }
      : { label: "Draft", tone: "info" },
    blocks,
    actions: sendActions(draft),
    textHint: draft.sent ? undefined : SEND_HINT,
    footer: draft.sent ? undefined : DRAFT_FOOTER,
    actionIds: heldActionIds(draft),
  };
}

/** One card per composed draft: who it goes to, what it says, and Send. */
export function buildEmailComposeCards(drafts: BotEmailDraft[]): Card[] {
  return drafts.map(buildDraftCard);
}
