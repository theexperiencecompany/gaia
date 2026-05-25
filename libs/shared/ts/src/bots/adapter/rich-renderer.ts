/**
 * Converts {@link RichMessage} objects to platform-appropriate text.
 *
 * Used by Slack and Telegram adapters that lack native rich-embed support.
 * Discord uses its own `EmbedBuilder` instead of this renderer.
 *
 * Slack and Telegram use different formatting syntax:
 * - **Slack**: `*bold*`, `_italic_`, `<url|label>` (mrkdwn)
 * - **Telegram**: `**bold**`, `_italic_`, `[label](url)` (CommonMark — the
 *   adapter then runs this through `renderForPlatform` to produce Telegram HTML)
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
  // Discord and Telegram consume CommonMark, where ** is bold (Telegram's HTML
  // converter turns ** into <b>). Slack mrkdwn and WhatsApp use *bold*.
  return platform === "discord" || platform === "telegram"
    ? `**${text}**`
    : `*${text}*`;
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
  // Slack: <url|label>. WhatsApp has no masked-link syntax — it auto-links
  // bare URLs, so render "label (url)" (matching convertToWhatsAppMarkdown).
  // Telegram/Discord render CommonMark "[label](url)".
  if (platform === "slack") return `<${url}|${label}>`;
  if (platform === "whatsapp") return `${label} (${url})`;
  return `[${label}](${url})`;
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
