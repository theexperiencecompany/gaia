import type { EmailThreadData, EmailThreadMessage } from "../../../chat/types";
import { truncateText } from "../../../utils/formatters";
import { htmlToPlainText } from "../../utils/formatters";
import type { Card, CardBlock, CardQuoteBlock } from "../types";
import { joinMeta } from "./card-parts";
import { countLabel } from "./count-label";
import { emailTimeLabel, NO_SUBJECT, senderName } from "./email-format";

const THREAD_TITLE = "Thread";
/** The latest messages carry the conversation; earlier ones are counted, not quoted. */
const MAX_QUOTED_MESSAGES = 5;
/** Enough of each message to follow the thread; the full text is in Gmail. */
const MESSAGE_PREVIEW_MAX = 600;

/** The message as plain text: Gmail's text part, else its HTML stripped, else the snippet. */
function messageText(message: EmailThreadMessage): string {
  const text =
    message.content?.text ||
    htmlToPlainText(message.content?.html || message.body || "") ||
    message.snippet ||
    "";
  return truncateText(text.trim(), MESSAGE_PREVIEW_MAX);
}

function messageQuote(message: EmailThreadMessage): CardQuoteBlock | null {
  const text = messageText(message);
  if (!text) return null;
  const sender = message.from_name || message.from;
  return {
    kind: "quote",
    markdown: text,
    collapsible: true,
    cite: joinMeta([
      sender ? senderName(sender) : undefined,
      emailTimeLabel(message.time),
    ]),
  };
}

/** An email thread: its subject, then its latest messages quoted, each cited by sender and time. */
export function buildEmailThreadCards(thread: EmailThreadData): Card[] {
  const messages = thread.messages ?? [];
  if (messages.length === 0) return [];
  const total = Math.max(thread.messages_count ?? 0, messages.length);
  const quoted = messages
    .slice(-MAX_QUOTED_MESSAGES)
    .map(messageQuote)
    .filter((quote): quote is CardQuoteBlock => quote !== null);
  const earlier = total - Math.min(messages.length, MAX_QUOTED_MESSAGES);
  const subject = thread.subject || messages[0].subject || NO_SUBJECT;
  const blocks: CardBlock[] = [{ kind: "text", markdown: `**${subject}**` }];
  if (earlier > 0) {
    blocks.push({
      kind: "text",
      markdown: `_${countLabel(earlier, "earlier message")} not shown_`,
    });
  }
  blocks.push(...quoted);
  return [
    {
      title: joinMeta([THREAD_TITLE, countLabel(total, "message")]),
      accent: "brand",
      blocks,
      actions: [],
    },
  ];
}
