/**
 * Renders a shared {@link Card} as a Telegram rich message (Bot API 10.1+):
 * a heading, labelled values as a compact table, long content in collapsible
 * quotes, and the card's buttons as styled button rows inside the message.
 *
 * Text arrives as CommonMark and goes through the one platform conversion
 * (`renderForPlatform`); its line breaks become `<br>`, since rich HTML lays out
 * blocks itself. Reference: https://core.telegram.org/bots/api#rich-messages
 *
 * @module
 */
import {
  type Card,
  type CardBlock,
  type CardCodeBlock,
  type CardImageBlock,
  type CardInvokeStyle,
  type CardLinkAction,
  type CardListBlock,
  type CardQuoteBlock,
  encodeCardActionData,
  encodeCardReplyData,
  escapeHtml,
  escapeHtmlAttr,
  invokeActionRows,
  linkActions,
  renderForPlatform,
  replyActions,
} from "@gaia/shared/bots";
import type { InputRichMessage } from "grammy/types";

/** Telegram refuses non-https button URLs (a dev `localhost` link included). */
const BUTTON_URL_PREFIX = "https://";

/** Approve / Send / Done read as go-ahead green; Deny as red. */
const BUTTON_STYLE: Record<CardInvokeStyle, string> = {
  primary: "success",
  danger: "danger",
};

/** CommonMark to rich HTML: the shared Telegram conversion, line breaks as `<br>`. */
export function richText(markdown: string): string {
  return renderForPlatform(markdown, "telegram").replaceAll("\n", "<br>");
}

function fieldsTable(block: Extract<CardBlock, { kind: "fields" }>): string {
  const rows = block.fields
    .map(
      (field) =>
        `<tr><td><b>${escapeHtml(field.label)}</b></td><td>${richText(field.value)}</td></tr>`,
    )
    .join("");
  return `<table compact>${rows}</table>`;
}

function quote(block: CardQuoteBlock): string {
  const cite = block.cite ? `<cite>${escapeHtml(block.cite)}</cite>` : "";
  const open = block.collapsible ? "<blockquote expandable>" : "<blockquote>";
  return `${open}${richText(block.markdown)}${cite}</blockquote>`;
}

function listItems(block: CardListBlock): string {
  const items = block.items
    .map((item) => {
      const title = item.url
        ? `<a href="${escapeHtmlAttr(item.url)}"><b>${escapeHtml(item.title)}</b></a>`
        : `<b>${escapeHtml(item.title)}</b>`;
      const meta = item.meta ? `<br><i>${escapeHtml(item.meta)}</i>` : "";
      const body = item.body ? `<br>${escapeHtml(item.body)}` : "";
      return `<li>${title}${meta}${body}</li>`;
    })
    .join("");
  const more =
    block.hiddenCount > 0 ? `<p><i>and ${block.hiddenCount} more</i></p>` : "";
  return `<ul>${items}</ul>${more}`;
}

function codeBlock(block: CardCodeBlock): string {
  const language = block.language
    ? ` class="language-${escapeHtmlAttr(block.language)}"`
    : "";
  return `<pre><code${language}>${escapeHtml(block.code)}</code></pre>`;
}

/** Media blocks take only http(s) URLs; anything else stays a visible link. */
function imageBlock(block: CardImageBlock): string {
  if (!block.url.startsWith(BUTTON_URL_PREFIX)) {
    return `<p><a href="${escapeHtmlAttr(block.url)}">${escapeHtml(block.alt)}</a></p>`;
  }
  return `<figure><img src="${escapeHtmlAttr(block.url)}"/><figcaption>${escapeHtml(block.alt)}</figcaption></figure>`;
}

function renderBlock(block: CardBlock): string {
  switch (block.kind) {
    case "text":
      return `<p>${richText(block.markdown)}</p>`;
    case "fields":
      return fieldsTable(block);
    case "quote":
      return quote(block);
    case "list":
      return listItems(block);
    case "code":
      return codeBlock(block);
    case "image":
      return imageBlock(block);
  }
}

function button(attrs: string, label: string): string {
  return `<tg-button ${attrs}>${escapeHtml(label)}</tg-button>`;
}

function buttonRow(buttons: string[]): string {
  return buttons.length > 0
    ? `<tg-button-row>${buttons.join("")}</tg-button-row>`
    : "";
}

function linkMarkup(links: CardLinkAction[]): string {
  return links
    .map((link) =>
      link.url.startsWith(BUTTON_URL_PREFIX)
        ? buttonRow([
            button(
              `type="url" style="primary" url="${escapeHtmlAttr(link.url)}"`,
              link.label,
            ),
          ])
        : // A link Telegram won't take as a button stays visible as text, URL included.
          `<p><a href="${escapeHtmlAttr(link.url)}">${escapeHtml(link.label)}</a><br><code>${escapeHtml(link.url)}</code></p>`,
    )
    .join("");
}

function actionMarkup(card: Card): string {
  const invokeRows = invokeActionRows(card).map((row) =>
    buttonRow(
      row.map((action) =>
        button(
          `type="callback_data"${action.style ? ` style="${BUTTON_STYLE[action.style]}"` : ""} data="${escapeHtmlAttr(encodeCardActionData(action.actionId))}"`,
          action.label,
        ),
      ),
    ),
  );
  const replyRow = buttonRow(
    replyActions(card).map((action) =>
      button(
        `type="callback_data" data="${escapeHtmlAttr(encodeCardReplyData(action.prompt))}"`,
        action.label,
      ),
    ),
  );
  return [...invokeRows, replyRow, linkMarkup(linkActions(card))].join("");
}

/** The card as a rich message, buttons included. */
export function renderTelegramCard(card: Card): InputRichMessage {
  const parts: string[] = [];
  if (card.author) parts.push(`<p><i>${escapeHtml(card.author.name)}</i></p>`);
  if (card.title) parts.push(`<h3>${escapeHtml(card.title)}</h3>`);
  parts.push(...card.blocks.map(renderBlock));
  parts.push(actionMarkup(card));
  if (card.footer) parts.push(`<footer>${escapeHtml(card.footer)}</footer>`);
  return { html: parts.join("") };
}
