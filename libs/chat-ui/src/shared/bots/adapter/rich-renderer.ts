/**
 * Converts {@link RichMessage} objects to platform-appropriate text.
 *
 * Used by Slack and Telegram adapters that lack native rich-embed support.
 * Discord uses its own `EmbedBuilder` instead of this renderer.
 *
 * Slack and Telegram use different formatting syntax:
 * - **Slack**: `*bold*`, `_italic_`, `<url|label>` (mrkdwn)
 * - **Telegram**: `**bold**`, `_italic_`, `[label](url)` (Markdown)
 *
 * @module
 */
import type { PlatformName, RichMessage } from "../types";

/**
 * Wraps text in bold syntax appropriate for the target platform.
 *
 * @param text - The text to make bold.
 * @param platform - The target platform.
 * @returns The bold-formatted text.
 */
function bold(text: string, platform: PlatformName): string {
  // Slack mrkdwn: *bold*, Telegram legacy Markdown: *bold*, Discord: **bold**
  return platform === "discord" ? `**${text}**` : `*${text}*`;
}

/**
 * Formats a hyperlink appropriate for the target platform.
 *
 * @param label - The display text.
 * @param url - The link URL.
 * @param platform - The target platform.
 * @returns The formatted hyperlink.
 */
function link(label: string, url: string, platform: PlatformName): string {
  return platform === "slack" ? `<${url}|${label}>` : `[${label}](${url})`;
}

/**
 * Renders a {@link RichMessage} as formatted text for the given platform.
 *
 * Layout:
 * ```
 * *Title*  (or **Title** on Telegram)
 * Description
 *
 * *Field 1*
 * value 1
 *
 * *Field 2*
 * value 2
 *
 * Link 1 | Link 2
 *
 * _footer text_
 * ```
 *
 * @param msg - The rich message to render.
 * @param platform - The target platform (defaults to `"telegram"`).
 * @returns A formatted text string suitable for the platform.
 */
export function richMessageToMarkdown(
  msg: RichMessage,
  platform: PlatformName = "telegram",
): string {
  const parts: string[] = [];

  if (msg.authorName) {
    parts.push(msg.authorName);
  }

  parts.push(bold(msg.title, platform));

  if (msg.description) {
    parts.push(msg.description);
  }

  for (const field of msg.fields) {
    parts.push(`${bold(field.name, platform)}\n${field.value}`);
  }

  if (msg.links && msg.links.length > 0) {
    const linkText = msg.links
      .map((l) => link(l.label, l.url, platform))
      .join(" | ");
    parts.push(linkText);
  }

  if (msg.footer) {
    parts.push(`_${msg.footer}_`);
  }

  return parts.join("\n\n");
}
