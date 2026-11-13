/**
 * Renders a {@link Card} as one CommonMark string.
 *
 * This is the card on every platform without a native card format (WhatsApp,
 * iMessage), and the exact text reported to the API as what the user was shown.
 * Links stay as `[label](url)`: the platform conversion happens once, at send
 * time, in `renderForPlatform`. Buttons cannot be tapped in text, so they are
 * left out and the card's `textHint` says what to reply instead.
 *
 * @module
 */
import { linkActions } from "./invoke";
import type {
  Card,
  CardBlock,
  CardCodeBlock,
  CardListBlock,
  CardQuoteBlock,
} from "./types";

const LINK_SEPARATOR = " | ";

/** A quote as CommonMark: every line behind `>`, the cite on its own line. */
export function quoteMarkdown(block: CardQuoteBlock): string {
  const lines = block.markdown.split("\n").map((line) => `> ${line}`);
  if (block.cite) lines.push(`> _${block.cite}_`);
  return lines.join("\n");
}

/** A list as CommonMark: the title (linked when it has a URL), then its meta and snippet. */
export function listMarkdown(block: CardListBlock): string {
  const lines = block.items.map((item) => {
    const title = item.url
      ? `[${item.title}](${item.url})`
      : `**${item.title}**`;
    const meta = item.meta ? `\n_${item.meta}_` : "";
    const body = item.body ? `\n${item.body}` : "";
    return `- ${title}${meta}${body}`;
  });
  if (block.hiddenCount > 0) lines.push(`_and ${block.hiddenCount} more_`);
  return lines.join("\n\n");
}

/** Code as a fenced CommonMark block. */
export function codeMarkdown(block: CardCodeBlock): string {
  return `\`\`\`${block.language ?? ""}\n${block.code}\n\`\`\``;
}

function renderBlock(block: CardBlock): string[] {
  if (block.kind === "text") return [block.markdown];
  if (block.kind === "quote") return [quoteMarkdown(block)];
  if (block.kind === "list") return [listMarkdown(block)];
  if (block.kind === "code") return [codeMarkdown(block)];
  if (block.kind === "image") return [`[${block.alt}](${block.url})`];
  return block.fields.map((field) => `**${field.label}**\n${field.value}`);
}

export function renderCardText(card: Card): string {
  const parts: string[] = [];
  if (card.author) parts.push(card.author.name);
  if (card.title) parts.push(`**${card.title}**`);
  parts.push(...card.blocks.flatMap(renderBlock));
  const links = linkActions(card);
  if (links.length > 0) {
    parts.push(
      links.map((link) => `[${link.label}](${link.url})`).join(LINK_SEPARATOR),
    );
  }
  if (card.textHint) parts.push(card.textHint);
  if (card.footer) parts.push(`_${card.footer}_`);
  return parts.join("\n\n");
}
