/**
 * Renders a shared {@link Card} as a Slack Block Kit message.
 *
 * @module
 */
import {
  type Card,
  type CardBlock,
  type CardInvokeAction,
  codeMarkdown,
  encodeCardReplyData,
  invokeActionRows,
  linkActions,
  listMarkdown,
  quoteMarkdown,
  renderCardText,
  renderForPlatform,
  replyActions,
  slackCardActionId,
} from "@gaia/shared/bots";
import type { types } from "@slack/bolt";

/** Block Kit limits (https://api.slack.com/reference/block-kit). */
const HEADER_TEXT_MAX = 150;
const BUTTON_TEXT_MAX = 75;
/** A section holds at most ten fields, laid out two to a row. */
const SECTION_FIELDS_MAX = 10;

export interface SlackCard {
  /** Notification and fallback text; Slack shows it where blocks can't render. */
  text: string;
  blocks: types.KnownBlock[];
}

function mrkdwn(markdown: string): types.MrkdwnElement {
  return { type: "mrkdwn", text: renderForPlatform(markdown, "slack") };
}

function buttonText(label: string): types.PlainTextElement {
  return { type: "plain_text", text: label.slice(0, BUTTON_TEXT_MAX) };
}

/** One object's invoke buttons as one actions block. */
function invokeBlock(row: CardInvokeAction[]): types.ActionsBlock {
  return {
    type: "actions",
    elements: row.map((action, position) => ({
      type: "button",
      text: buttonText(action.label),
      action_id: slackCardActionId(position),
      value: action.actionId,
      ...(action.style && { style: action.style }),
    })),
  };
}

function contentBlocks(block: CardBlock): types.KnownBlock[] {
  if (block.kind === "text") {
    return [{ type: "section", text: mrkdwn(block.markdown) }];
  }
  if (block.kind === "quote") {
    return [{ type: "section", text: mrkdwn(quoteMarkdown(block)) }];
  }
  if (block.kind === "list") {
    return [{ type: "section", text: mrkdwn(listMarkdown(block)) }];
  }
  if (block.kind === "code") {
    return [{ type: "section", text: mrkdwn(codeMarkdown(block)) }];
  }
  if (block.kind === "image") {
    return [{ type: "image", image_url: block.url, alt_text: block.alt }];
  }
  const sections: types.KnownBlock[] = [];
  for (
    let start = 0;
    start < block.fields.length;
    start += SECTION_FIELDS_MAX
  ) {
    sections.push({
      type: "section",
      fields: block.fields
        .slice(start, start + SECTION_FIELDS_MAX)
        .map((field) => mrkdwn(`**${field.label}**\n${field.value}`)),
    });
  }
  return sections;
}

export function renderSlackCard(card: Card): SlackCard {
  const blocks: types.KnownBlock[] = [];
  if (card.author) {
    blocks.push({
      type: "context",
      elements: [
        ...(card.author.iconUrl
          ? [
              {
                type: "image" as const,
                image_url: card.author.iconUrl,
                alt_text: card.author.name,
              },
            ]
          : []),
        { type: "plain_text", text: card.author.name },
      ],
    });
  }
  if (card.title) {
    blocks.push({
      type: "header",
      text: {
        type: "plain_text",
        text: card.title.slice(0, HEADER_TEXT_MAX),
      },
    });
  }
  blocks.push(...card.blocks.flatMap(contentBlocks));
  blocks.push(...invokeActionRows(card).map(invokeBlock));
  const replies = replyActions(card);
  if (replies.length > 0) {
    blocks.push({
      type: "actions",
      elements: replies.map((action, position) => ({
        type: "button",
        text: buttonText(action.label),
        action_id: slackCardActionId(position),
        value: encodeCardReplyData(action.prompt),
      })),
    });
  }
  const links = linkActions(card);
  if (links.length > 0) {
    blocks.push({
      type: "actions",
      elements: links.map((link, position) => ({
        type: "button",
        text: buttonText(link.label),
        url: link.url,
        action_id: slackCardActionId(position),
      })),
    });
  }
  if (card.footer) {
    blocks.push({ type: "context", elements: [mrkdwn(`_${card.footer}_`)] });
  }
  return {
    text: renderForPlatform(renderCardText(card), "slack"),
    blocks,
  };
}
