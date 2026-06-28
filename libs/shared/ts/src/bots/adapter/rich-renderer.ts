/**
 * Converts {@link RichMessage} objects to a single CommonMark string.
 *
 * Used by the Slack, Telegram, and WhatsApp adapters, which lack native
 * rich-embed support. Discord uses its own `EmbedBuilder` instead.
 *
 * This renderer is **platform-agnostic**: it always emits CommonMark
 * (`**bold**`, `[label](url)`, `_footer_`). The single platform conversion
 * happens at send time when the adapter passes the result through
 * `renderForPlatform`, so there is exactly one markdown chokepoint and field
 * values that themselves contain markdown are converted correctly.
 *
 * @module
 */
import type { RichMessage } from "../types";

/**
 * Renders a {@link RichMessage} as a CommonMark string.
 *
 * Layout:
 * ```
 * authorName
 *
 * **Title**
 *
 * Description
 *
 * **Field 1**
 * value 1
 *
 * **Field 2**
 * value 2
 *
 * [Link 1](url) | [Link 2](url)
 *
 * _footer text_
 * ```
 *
 * @param msg - The rich message to render.
 * @returns A CommonMark string, ready to be passed through `renderForPlatform`.
 */
export function richMessageToMarkdown(msg: RichMessage): string {
  const parts: string[] = [];

  if (msg.authorName) {
    parts.push(msg.authorName);
  }

  parts.push(`**${msg.title}**`);

  if (msg.description) {
    parts.push(msg.description);
  }

  for (const field of msg.fields) {
    parts.push(`**${field.name}**\n${field.value}`);
  }

  if (msg.links && msg.links.length > 0) {
    const linkText = msg.links.map((l) => `[${l.label}](${l.url})`).join(" | ");
    parts.push(linkText);
  }

  if (msg.footer) {
    parts.push(`_${msg.footer}_`);
  }

  return parts.join("\n\n");
}
