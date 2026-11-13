/**
 * A shared {@link Card} as a GAIA-themed Telegram widget (Bot API 10.4): the
 * card drawn inline in the chat as its own surface, its buttons working in
 * place. See {@link WIDGET_STYLE} for the theme and the tap round trip.
 *
 * A widget's code is fixed once sent, so the markup carries the whole card and
 * every state it can reach; only the settled badge arrives later, through the
 * chat state. The card's footer is the message caption: a caption under the
 * widget is where Telegram then draws the time, instead of over the widget.
 *
 * A card a widget cannot draw faithfully returns `null` and goes out as a rich
 * message instead: one with an image (a widget loads none) or
 * code (copied from a rich message's native code block), a link the widget
 * cannot open, or markup past the size limit.
 *
 * @module
 */
import { deflateSync } from "node:zlib";
import {
  type Card,
  type CardBlock,
  type CardLinkAction,
  type CardListBlock,
  type CardQuoteBlock,
  type CardStatus,
  encodeCardActionData,
  encodeCardReplyData,
  escapeHtml,
  escapeHtmlAttr,
  invokeActionRows,
  linkActions,
  replyActions,
} from "@gaia/shared/bots";
import { richText } from "../card";
import {
  WIDGET_SCRIPT,
  WIDGET_STYLE,
  type WidgetAnswer,
  type WidgetState,
  type WidgetStatus,
} from "./widget-shell";

/** Telegram's cap on a widget's HTML, in UTF-8 bytes. */
const WIDGET_HTML_MAX_BYTES = 32768;
/**
 * Telegram's cap is 4096 bytes after zlib level 9; Node's zlib can count a few
 * dozen bytes off the server's, so the budget keeps that margin.
 */
const WIDGET_COMPRESSED_BUDGET_BYTES = 3968;
const ZLIB_MAX_LEVEL = 9;
/** `openLink` takes https URLs of at most this many characters. */
const WIDGET_LINK_MAX_CHARS = 256;
const HTTPS_PREFIX = "https://";
/** The chat state and an answer are each a UTF-8 text of at most this many bytes. */
const WIDGET_DATA_MAX_BYTES = 1024;

const encoder = new TextEncoder();

function byteLength(text: string): number {
  return encoder.encode(text).length;
}

function isOpenable(link: CardLinkAction): boolean {
  return (
    link.url.startsWith(HTTPS_PREFIX) &&
    link.url.length <= WIDGET_LINK_MAX_CHARS
  );
}

/** Whether the widget can draw the card as the rich message would show it. */
function fitsWidget(card: Card): boolean {
  const drawable = card.blocks.every(
    (block) => block.kind !== "image" && block.kind !== "code",
  );
  return drawable && linkActions(card).every(isOpenable);
}

function fields(block: Extract<CardBlock, { kind: "fields" }>): string {
  const rows = block.fields
    .map(
      (field) =>
        `<div class="row"><span class="k">${escapeHtml(field.label)}</span><span>${richText(field.value)}</span></div>`,
    )
    .join("");
  return `<div class="box">${rows}</div>`;
}

function quote(block: CardQuoteBlock): string {
  const cite = block.cite
    ? `<div class="cite">${escapeHtml(block.cite)}</div>`
    : "";
  const body = `<div class="q">${richText(block.markdown)}</div>`;
  if (!block.collapsible) return `<div class="box">${cite}${body}</div>`;
  return `<div class="box fold">${cite}${body}<button class="t" onclick="fold(this)">Show more</button></div>`;
}

function list(block: CardListBlock): string {
  const items = block.items
    .map((item) => {
      const title = item.url
        ? `<a href="${escapeHtmlAttr(item.url)}"><b>${escapeHtml(item.title)}</b></a>`
        : `<b>${escapeHtml(item.title)}</b>`;
      const meta = item.meta
        ? `<div class="m">${escapeHtml(item.meta)}</div>`
        : "";
      const body = item.body
        ? `<div class="sn">${escapeHtml(item.body)}</div>`
        : "";
      return `<div class="it">${title}${meta}${body}</div>`;
    })
    .join("");
  const more =
    block.hiddenCount > 0
      ? `<div class="more">and ${block.hiddenCount} more</div>`
      : "";
  return `<div class="box">${items}${more}</div>`;
}

function renderBlock(block: CardBlock): string {
  switch (block.kind) {
    case "text":
      return `<p>${richText(block.markdown)}</p>`;
    case "fields":
      return fields(block);
    case "quote":
      return quote(block);
    case "list":
      return list(block);
    case "code":
    case "image":
      // Never reached: fitsWidget sends such a card as a rich message.
      return "";
  }
}

function requestButton(wireId: string, label: string, style: string): string {
  const cls = style ? ` class="${style}"` : "";
  return `<button${cls} data-q="${escapeHtmlAttr(wireId)}" onclick="q(this)">${escapeHtml(label)}</button>`;
}

/** The buttons, which the script hides once the card settles. */
function actions(card: Card): string {
  const invokeRows = invokeActionRows(card);
  const rows = invokeRows.map(
    (row) =>
      `<div class="btns">${row
        .map((action) =>
          requestButton(
            encodeCardActionData(action.actionId),
            action.label,
            action.style === "primary"
              ? "p"
              : action.style === "danger"
                ? "d"
                : "",
          ),
        )
        .join("")}</div>`,
  );
  // A link is the card's main action unless the card has buttons of its own.
  const linkStyle = invokeRows.length > 0 ? "" : ' class="p"';
  const links = linkActions(card).map(
    (link) =>
      `<div class="btns"><button${linkStyle} data-u="${escapeHtmlAttr(link.url)}" onclick="u(this)">${escapeHtml(link.label)}</button></div>`,
  );
  const replies = replyActions(card).map((action) =>
    requestButton(encodeCardReplyData(action.prompt), action.label, "r"),
  );
  const replyRow =
    replies.length > 0 ? `<div class="btns">${replies.join("")}</div>` : "";
  const all = [...rows, ...links, replyRow].join("");
  return all ? `<div class="acts">${all}</div>` : "";
}

function badge(status: CardStatus | undefined): string {
  return status
    ? `<span class="chip ${status.tone}" id="st">${escapeHtml(status.label)}</span>`
    : `<span class="chip" id="st" hidden></span>`;
}

function markup(card: Card): string {
  const parts = [
    `<div id="c">`,
    badge(card.status),
    card.title ? `<h1>${escapeHtml(card.title)}</h1>` : "",
    ...card.blocks.map(renderBlock),
    actions(card),
    `<div class="note" id="n" hidden></div>`,
    `</div>`,
  ];
  return `${WIDGET_STYLE}${parts.join("")}${WIDGET_SCRIPT}`;
}

function withinLimits(html: string): boolean {
  if (byteLength(html) > WIDGET_HTML_MAX_BYTES) return false;
  const compressed = deflateSync(html, { level: ZLIB_MAX_LEVEL });
  return compressed.length <= WIDGET_COMPRESSED_BUDGET_BYTES;
}

/** A card as `sendWidget` takes it. */
export interface CardWidget {
  html: string;
  /** The card's footer, plain text. */
  caption?: string;
}

/** The card as a widget, or `null` when it goes out as a rich message. */
export function renderCardWidget(card: Card): CardWidget | null {
  if (!fitsWidget(card)) return null;
  const html = markup(card);
  if (!withinLimits(html)) return null;
  return { html, ...(card.footer && { caption: card.footer }) };
}

function wireStatus(status: CardStatus): WidgetStatus {
  return { l: status.label, t: status.tone };
}

/** The chat state that draws a settled card's badge, or `undefined` when it has none. */
export function widgetState(card: Card | null): string | undefined {
  if (!card?.status) return undefined;
  const state: WidgetState = { s: wireStatus(card.status) };
  return JSON.stringify(state);
}

/**
 * The answer to a widget tap: the outcome's line, and the settled badge so the
 * widget redraws at once. The line is cut to fit the 1024-byte answer.
 */
export function widgetAnswer(message: string, settled: Card | null): string {
  const status = settled?.status ? wireStatus(settled.status) : undefined;
  let shown = message;
  let text = JSON.stringify({ m: shown, s: status } satisfies WidgetAnswer);
  while (byteLength(text) > WIDGET_DATA_MAX_BYTES && shown.length > 0) {
    shown = shown.slice(0, Math.floor(shown.length / 2));
    text = JSON.stringify({ m: shown, s: status } satisfies WidgetAnswer);
  }
  return text;
}
