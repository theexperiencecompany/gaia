/**
 * Pure display formatters for bot responses.
 *
 * These are data-in, string-out functions with no side effects.
 * They are used by the shared command handlers in commands.ts
 * and can also be called directly when assembling custom responses.
 *
 * formatBotError is the single error formatter for all bots: it words the
 * reason classifyBotFailure gives, then falls back to generic Error messages.
 */
import { slackifyMarkdown } from "slackify-markdown";
import type {
  BotConversation,
  BotTodo,
  BotWorkflow,
  PlatformName,
} from "../types";
import { BOT_FAILURE_REASON, classifyBotFailure } from "./failure-reasons";
import { getErrorReason } from "./logger";
import { isTableRow, isTableSeparator, PLATFORM_DISPLAY_NAMES } from "./text";

/**
 * Formats a workflow for display in a bot message.
 */
export function formatWorkflow(workflow: BotWorkflow): string {
  const status =
    workflow.status === "active"
      ? "✅"
      : workflow.status === "draft"
        ? "📝"
        : "⏸️";
  return `${status} **${workflow.name}**\nID: \`${workflow.id}\`\n${workflow.description || "No description"}`;
}

/**
 * Formats a list of workflows for display.
 */
export function formatWorkflowList(workflows: BotWorkflow[]): string {
  if (workflows.length === 0) {
    return "No workflows found. Create one with `/workflow create`";
  }

  return workflows.map(formatWorkflow).join("\n\n");
}

/**
 * Formats a todo for display in a bot message.
 */
export function formatTodo(todo: BotTodo): string {
  const checkbox = todo.completed ? "☑️" : "⬜";
  const priority = todo.priority ? ` [${todo.priority.toUpperCase()}]` : "";
  const dueDate = todo.due_date
    ? ` | Due: ${new Date(todo.due_date).toLocaleDateString()}`
    : "";

  return `${checkbox} **${todo.title}**${priority}\nID: \`${todo.id}\`${dueDate}`;
}

/**
 * Formats a list of todos for display.
 */
export function formatTodoList(todos: BotTodo[]): string {
  if (todos.length === 0) {
    return "No todos found. Create one with `/todo add`";
  }

  return todos.map(formatTodo).join("\n\n");
}

/**
 * Formats a conversation for display.
 */
export function formatConversation(
  conversation: BotConversation,
  baseUrl: string,
): string {
  const title = conversation.title || "Untitled Conversation";
  const url = `${baseUrl}/c/${conversation.conversation_id}`;
  const messageCount = conversation.message_count
    ? ` (${conversation.message_count} messages)`
    : "";

  return `💬 **${title}**${messageCount}\n🔗 ${url}`;
}

/**
 * Formats a list of conversations for display.
 */
export function formatConversationList(
  conversations: BotConversation[],
  baseUrl: string,
): string {
  if (conversations.length === 0) {
    return "No conversations found.";
  }

  return conversations.map((c) => formatConversation(c, baseUrl)).join("\n\n");
}

// ---------------------------------------------------------------------------
// Markdown conversion utilities
// ---------------------------------------------------------------------------

/**
 * Applies a text transformation only to segments outside fenced code blocks.
 * Preserves ``` ... ``` blocks unchanged so code is never mangled.
 */
function applyOutsideCodeBlocks(
  text: string,
  transform: (segment: string) => string,
): string {
  const parts: string[] = [];
  let lastIndex = 0;
  for (const match of text.matchAll(/```[\s\S]*?```/g)) {
    parts.push(transform(text.slice(lastIndex, match.index)));
    parts.push(match[0]);
    lastIndex = (match.index ?? 0) + match[0].length;
  }
  parts.push(transform(text.slice(lastIndex)));
  return parts.join("");
}

/**
 * Escapes the three characters special in Telegram HTML body text: `&`, `<`, `>`. Everything
 * else is literal in HTML mode, which is why it's immune to legacy-Markdown's underscore/URL
 * breakage. Slack's mrkdwn control-character escaping needs the same three entities, so
 * {@link convertToSlackMrkdwn} reuses this helper.
 */
export function escapeHtml(text: string): string {
  return text
    .replaceAll(/&/g, "&amp;")
    .replaceAll(/</g, "&lt;")
    .replaceAll(/>/g, "&gt;");
}

/**
 * Escapes a string for use inside an HTML attribute value (a link `href`):
 * {@link escapeHtml} plus the double quote that would otherwise close the
 * attribute.
 */
export function escapeHtmlAttr(text: string): string {
  return escapeHtml(text).replaceAll(/"/g, "&quot;");
}

/**
 * Best-effort conversion of Telegram HTML back to plain text. Used only as the
 * fallback when Telegram rejects an HTML message — which, with fully escaped
 * output, should essentially never happen. Strips tags and decodes the
 * entities {@link escapeHtml}/{@link escapeHtmlAttr} can introduce, so the user
 * sees clean text instead of literal `<b>` tags. `&amp;` is decoded last so a
 * literal `&lt;` in the source does not get double-decoded.
 */
export function htmlToPlainText(html: string): string {
  return html
    .replaceAll(/<[^>]+>/g, "")
    .replaceAll(/&lt;/g, "<")
    .replaceAll(/&gt;/g, ">")
    .replaceAll(/&quot;/g, '"')
    .replaceAll(/&amp;/g, "&");
}

/** Renders a GFM table as a column-aligned monospace `<pre>` block. */
function renderTelegramTable(block: string): string {
  const cells = (line: string): string[] =>
    line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((c) => c.trim());
  const lines = block.trim().split(/\r?\n/);
  const header = cells(lines[0] ?? "");
  const body = lines.slice(2).map(cells); // lines[1] is the |---| separator
  const colCount = Math.max(header.length, ...body.map((r) => r.length));
  const widths = Array.from({ length: colCount }, (_, i) =>
    Math.max(header[i]?.length ?? 0, ...body.map((r) => r[i]?.length ?? 0), 0),
  );
  const fmt = (row: string[]): string =>
    widths
      .map((w, i) => (row[i] ?? "").padEnd(w))
      .join("  ")
      .trimEnd();
  const rule = widths.map((w) => "─".repeat(w)).join("  ");
  const rendered = [fmt(header), rule, ...body.map(fmt)].join("\n");
  return `<pre>${escapeHtml(rendered)}</pre>`;
}

/**
 * Stashes GFM table blocks (a header row, a `|---|` separator, then body rows)
 * as monospace `<pre>` placeholders. Detection is line-by-line with plain string
 * checks — no backtracking-prone regex — so adversarial input can never cause
 * super-linear runtime (Telegram HTML has no `<table>` tag).
 */
function stashTables(text: string, hold: (html: string) => string): string {
  const lines = text.split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const header = lines[i] ?? "";
    if (isTableRow(header) && isTableSeparator(lines[i + 1] ?? "")) {
      const block = [header, lines[i + 1] ?? ""];
      let j = i + 2;
      while (j < lines.length && isTableRow(lines[j] ?? "")) {
        block.push(lines[j] ?? "");
        j += 1;
      }
      out.push(hold(renderTelegramTable(block.join("\n"))));
      i = j;
    } else {
      out.push(header);
      i += 1;
    }
  }
  return out.join("\n");
}

/** A blockquote longer than this many lines or characters becomes collapsible. */
const TELEGRAM_BLOCKQUOTE_EXPANDABLE_LINES = 4;
const TELEGRAM_BLOCKQUOTE_EXPANDABLE_CHARS = 300;

/**
 * Wraps runs of consecutive blockquote lines (already HTML-escaped, so the
 * marker reads `&gt;`) into Telegram `<blockquote>` tags, dropping the marker.
 * Long quotes use `<blockquote expandable>` so the client collapses them. Inner
 * inline emphasis is applied by the pass that runs after this one.
 */
function wrapTelegramBlockquotes(text: string): string {
  // CommonMark allows up to 3 spaces of indentation before the `>` marker.
  const QUOTE_MARKER = /^[ \t]{0,3}&gt;[ \t]?/;
  const isQuote = (line: string): boolean => QUOTE_MARKER.test(line);
  const lines = text.split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    if (!isQuote(lines[i] ?? "")) {
      out.push(lines[i] ?? "");
      i += 1;
      continue;
    }
    const quoted: string[] = [];
    while (i < lines.length && isQuote(lines[i] ?? "")) {
      quoted.push((lines[i] ?? "").replace(QUOTE_MARKER, ""));
      i += 1;
    }
    const inner = quoted.join("\n");
    const expandable =
      quoted.length > TELEGRAM_BLOCKQUOTE_EXPANDABLE_LINES ||
      inner.length > TELEGRAM_BLOCKQUOTE_EXPANDABLE_CHARS;
    out.push(
      expandable
        ? `<blockquote expandable>${inner}</blockquote>`
        : `<blockquote>${inner}</blockquote>`,
    );
  }
  return out.join("\n");
}

/**
 * Converts the CommonMark the agent emits for Telegram into Telegram's **HTML** parse mode
 * (https://core.telegram.org/bots/api#html-style), chosen because its only special characters
 * are `&`, `<`, `>` — legacy Markdown italicized `..._x_...` inside auth-token URLs and
 * silently dropped the underscores (see the formatter tests).
 *
 * Strategy: stash code spans/blocks/links as placeholders, HTML-escape the rest, translate
 * surviving markdown to Telegram tags (no heading/list tags, so headings→bold, bullets→•), then splice placeholders back.
 */
export function convertToTelegramHtml(text: string): string {
  const stash: string[] = [];
  const hold = (html: string): string => {
    stash.push(html);
    return `\uE000${stash.length - 1}\uE000`;
  };

  let out = text
    // Fenced code: ```lang\n…``` → <pre>[<code class="language-…">]…</pre>
    .replaceAll(/```([\w+-]+)?[ \t]*\r?\n?([\s\S]*?)```/g, (_m, lang, code) => {
      const body = escapeHtml((code as string).replace(/\n$/, ""));
      return hold(
        lang
          ? `<pre><code class="language-${lang}">${body}</code></pre>`
          : `<pre>${body}</pre>`,
      );
    })
    // Inline code: `…`
    .replaceAll(/`([^`\n]+)`/g, (_m, code) =>
      hold(`<code>${escapeHtml(code as string)}</code>`),
    )
    // Masked links: [label](url) → <a href="url">label</a>
    .replaceAll(/\[([^\]\n]{1,500})\]\(([^)\s]{1,2048})\)/g, (_m, label, url) =>
      hold(
        `<a href="${escapeHtmlAttr(url as string)}">${escapeHtml(label as string)}</a>`,
      ),
    );

  // GFM tables → monospace <pre> placeholders (Telegram HTML has no table tags).
  out = stashTables(out, hold);

  out = escapeHtml(out)
    // Block structure (line-anchored). `>` is `&gt;` now, after escaping.
    .replaceAll(/^(\s*)[-*+][ \t]+/gm, "$1• ") // bullets → •
    .replaceAll(/^#{1,6}[ \t]+(.+)$/gm, "<b>$1</b>") // headings → bold
    .replaceAll(/^[-_]{3,}$/gm, ""); // horizontal rule → remove

  // Blockquotes → <blockquote>/<blockquote expandable> (Telegram rich
  // formatting), before the inline pass so emphasis inside a quote still renders.
  out = wrapTelegramBlockquotes(out);

  out = out
    // Inline emphasis. Bold before italic so `**` is consumed first.
    .replaceAll(/\*\*\*([^*\n]+?)\*\*\*/g, "<b><i>$1</i></b>") // ***x***
    .replaceAll(/\*\*([^*\n]+?)\*\*/g, "<b>$1</b>") // **x**
    .replaceAll(/__([^_\n]+?)__/g, "<b>$1</b>") // __x__
    .replaceAll(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, "<i>$1</i>") // *x*
    .replaceAll(/(?<!\w)_([^_\n]+?)_(?!\w)/g, "<i>$1</i>") // _x_ (skips snake_case)
    .replaceAll(/~~([^~\n]+?)~~/g, "<s>$1</s>"); // ~~x~~

  // Loop resolving placeholders so a stashed table containing a stashed link (nested) is fully
  // spliced back in; loop only while a real placeholder remains AND each pass makes progress,
  // so a stray U+E000 in source text (not a valid token) can never spin forever and wedge the event loop.
  let result = out;
  let previous = "";
  while (result !== previous && /\uE000\d+\uE000/.test(result)) {
    previous = result;
    result = result.replaceAll(
      /\uE000(\d+)\uE000/g,
      (_m, i) => stash[Number(i)] ?? "",
    );
  }
  return result;
}

/**
 * Converts standard CommonMark Markdown to Slack mrkdwn via the maintained `slackify-markdown`
 * library (Unified/Remark based), replacing the previous hand-rolled regex converter — it
 * correctly handles bold/strike/links/headings/lists/blockquotes/code/tables and Slack
 * control-character escaping, including edge cases (escaped backticks, nested emphasis, pipes
 * in prose) the regex version got wrong. An empty string passes through untouched so streaming
 * chunks never throw.
 */
export function convertToSlackMrkdwn(text: string): string {
  if (!text) return text;
  return slackifyMarkdown(text).trimEnd();
}

/**
 * Converts standard CommonMark Markdown to WhatsApp-compatible formatting.
 *
 * WhatsApp supports: `*bold*`, `_italic_`, `~strikethrough~`, `` `code` ``,
 * ` ```code``` `. Links are shown as bare URLs (WhatsApp auto-links them).
 *
 * Converts `**bold**` → `*bold*`, `[label](url)` → `label (url)`,
 * strips `# headers` to bold, strips blockquote `>` prefixes and horizontal rules.
 * Code blocks are preserved unchanged.
 */
export function convertToWhatsAppMarkdown(text: string): string {
  return applyOutsideCodeBlocks(
    text,
    (segment) =>
      segment
        // Headings FIRST so content is wrapped in `*` before the bold rule sees it — otherwise
        // `### **Heading**` becomes `### *Heading*` after bold, then `**Heading**` once heading
        // wraps the already-emphasised content, re-introducing the double asterisks we removed.
        .replaceAll(/^#{1,6}[ \t]+(\S[^\n]*)$/gm, "*$1*") // # Heading → *Heading*
        // Horizontal-rule remover MUST run before the bold rule — otherwise `***` on its own
        // line followed by `**Heading**` lets the bold regex's `[^*]` greedy-match across the
        // `***` boundary into `**X**`, splitting the heading and leaving stray `**` glyphs.
        .replaceAll(/^[-_*]{3,}$/gm, "") // --- / ___ / *** → remove
        // Bold rules: keep ``[^*\n]`` (no newlines) so a single ``**`` opener
        // cannot reach across blank lines and accidentally pair with the
        // opener of a SEPARATE bold span.
        .replaceAll(/\*\*\*([^*\n]+)\*\*\*/g, "*$1*") // ***bold italic*** → *bold*
        .replaceAll(/\*\*([^*\n]+)\*\*/g, "*$1*") // **bold** → *bold*
        .replaceAll(/\[([^\]]{1,500})\]\(([^)]{1,2048})\)/g, "$1 ($2)") // [label](url) → label (url)
        .replaceAll(/^([ \t]*)[*\-+][ \t]+/gm, "$1• ") // - / * / + bullet → •
        .replaceAll(/^>[ \t]*/gm, ""), // > quote → strip prefix
  );
}

/**
 * iMessage renders no markup at all, so every markdown construct degrades to
 * plain text: emphasis markers are stripped, links become `label (url)`,
 * headings/quotes lose their prefixes. Fenced code blocks are preserved
 * verbatim (content matters more than the stray backticks).
 */
export function convertToImessageText(text: string): string {
  return applyOutsideCodeBlocks(text, (segment) =>
    segment
      .replaceAll(/^#{1,6}[ \t]+(\S[^\n]*)$/gm, "$1")
      .replaceAll(/^[-_*]{3,}$/gm, "")
      .replaceAll(/\*\*\*([^*\n]+)\*\*\*/g, "$1")
      .replaceAll(/\*\*([^*\n]+)\*\*/g, "$1")
      .replaceAll(/`([^`\n]+)`/g, "$1")
      .replaceAll(/\[([^\]]{1,500})\]\(([^)]{1,2048})\)/g, "$1 ($2)")
      .replaceAll(/^([ \t]*)[*\-+][ \t]+/gm, "$1• ")
      .replaceAll(/^>[ \t]*/gm, ""),
  );
}

/**
 * Discord renders CommonMark natively (bold, italic, headings, lists, code,
 * quotes), so the only transform it needs is masked links: Discord shows
 * `[label](url)` literally in regular message content — masked links render
 * only inside embeds — whereas bare URLs auto-link. Convert masked links to
 * `label (url)` so they stay clickable, and leave everything else untouched.
 */
export function convertToDiscordMarkdown(text: string): string {
  return applyOutsideCodeBlocks(
    text,
    (segment) =>
      segment.replaceAll(/\[([^\]]{1,500})\]\(([^)]{1,2048})\)/g, "$1 ($2)"), // [label](url) → label (url)
  );
}

/**
 * Single source of truth mapping each platform to its Markdown converter.
 *
 * This is the centralization point: shared code (streaming, adapters) renders
 * outbound text through ``PLATFORM_MARKDOWN[platform]`` instead of each adapter
 * calling its ``convertTo<Platform>Markdown`` function inline. Adding a platform
 * means adding one entry here, not sprinkling conversion calls across adapters.
 */
export const PLATFORM_MARKDOWN: Record<PlatformName, (text: string) => string> =
  {
    discord: convertToDiscordMarkdown,
    slack: convertToSlackMrkdwn,
    telegram: convertToTelegramHtml,
    whatsapp: convertToWhatsAppMarkdown,
    imessage: convertToImessageText,
  };

/**
 * Renders outbound text into the target platform's Markdown dialect.
 *
 * The single chokepoint used by adapter non-streaming sends (RichMessageTarget
 * ``send``/``sendEphemeral``/``edit``, context-menu and command replies). Keeps
 * conversion out of the adapters: they call this one shared helper instead of
 * their platform-specific ``convertTo<Platform>Markdown``.
 */
export function renderForPlatform(
  text: string,
  platform: PlatformName,
): string {
  return PLATFORM_MARKDOWN[platform](text);
}

/**
 * The single canonical "link your account" prompt, used by both `/auth` and every adapter's
 * streaming `onAuthError` path on all four platforms, replacing each adapter's previously
 * divergent copy.
 *
 * Shown as a **bare** URL on purpose — copy-pasteable and auto-linked on a real public domain,
 * whereas Telegram won't linkify `<a href>` for non-public hosts like `localhost`, so a masked
 * link would render as dead text in dev. Send it through `renderForPlatform` for the heading bold.
 */
export function buildAuthLinkMessage(authUrl: string): string {
  return (
    "**Link your account to GAIA**\n\n" +
    "Tap below to sign in. Once you're connected, you can use everything right here.\n" +
    `${authUrl}`
  );
}

export function buildPlanRequiredMessage(pricingUrl: string): string {
  return (
    "🔒 **This platform is part of GAIA Pro**\n\n" +
    "Upgrade to keep chatting here.\n" +
    `${pricingUrl}`
  );
}

/** Shared help text and usage strings for text-based command platforms. */
export const COMMAND_HELP = {
  general: `🤖 **Welcome to GAIA**

**First Time? Start Here:**
1. /auth - Link your account
2. /status - Check if linked
3. /gaia <message> - Start chatting!

**Quick Commands:**
• /help - This message
• /settings - View account settings
• /new - Fresh conversation
• /todo - Manage todos
• /workflow - Run workflows
• /conversations - Chat history

Type /help <command> for details.`,
  todo:
    "Available commands:\n" +
    "/todo list - List your todos\n" +
    "/todo add <title> - Create a new todo\n" +
    "/todo complete <id> - Mark todo as complete\n" +
    "/todo delete <id> - Delete a todo",
  workflow:
    "Available commands:\n" +
    "/workflow list - List all workflows\n" +
    "/workflow get <id> - Get workflow details\n" +
    "/workflow execute <id> - Execute a workflow\n" +
    "/workflow delete <id> - Delete a workflow\n" +
    "/workflow create <name> <description> - Create a workflow",
  todoUsage: {
    add: "Usage: /todo add <title>",
    complete: "Usage: /todo complete <todo-id>",
    delete: "Usage: /todo delete <todo-id>",
  },
  workflowUsage: {
    get: "Usage: /workflow get <workflow-id>",
    execute: "Usage: /workflow execute <workflow-id>",
    delete: "Usage: /workflow delete <workflow-id>",
  },
};

/**
 * The user-facing message the API sent with an error response, if it sent one.
 *
 * Every non-2xx body is the flat error envelope, and its `message` is the
 * copy to show: `RateLimitExceededException` composes copy naming the wall
 * that was hit ("You've used today's AI usage allowance. Upgrade to Pro for
 * higher limits."), which is the only place that distinction exists.
 */
function serverMessage(error: unknown): string | null {
  const candidate = getErrorReason(error).message;
  return typeof candidate === "string" && candidate.trim()
    ? candidate.trim()
    : null;
}

/** The actionable reply when the platform account has no GAIA user behind it. */
function buildAccountNotLinkedMessage(platform?: PlatformName): string {
  const account = platform
    ? `Your ${PLATFORM_DISPLAY_NAMES[platform]} account`
    : "Your account";
  return `🔗 ${account} isn't linked to GAIA yet. Send /auth to link it.`;
}

/**
 * Formats an error message for user display. Pure: the caller records the
 * failure (recordBotFailure) before showing this.
 */
export function formatBotError(
  error: unknown,
  platform?: PlatformName,
): string {
  const reason = classifyBotFailure(error);

  if (reason === BOT_FAILURE_REASON.ACCOUNT_NOT_LINKED) {
    return buildAccountNotLinkedMessage(platform);
  }

  if (reason === BOT_FAILURE_REASON.BOT_API_KEY_INVALID) {
    return "❌ This bot can't reach GAIA right now. We've been alerted; please try again later.";
  }

  if (reason === BOT_FAILURE_REASON.UNAUTHORIZED) {
    return "❌ Authentication required. Use `/auth` to link your account.";
  }

  if (reason === BOT_FAILURE_REASON.NOT_FOUND) {
    return "❌ Not found. Please check the ID and try again.";
  }

  if (reason === BOT_FAILURE_REASON.RATE_LIMITED) {
    // Three different walls return 429 (flat anti-spam, plan message quota, daily AI-usage
    // budget) and only the body says which; waiting never fixes an exhausted allowance.
    const fromServer = serverMessage(error);
    return fromServer
      ? `⏳ ${fromServer}`
      : "⏳ You're sending messages too fast. Please wait a moment and try again.";
  }

  const message = error instanceof Error ? error.message : String(error ?? "");

  if (message.includes("timed out") || message.includes("timeout")) {
    return "⏳ The request timed out. The server may be busy. Please try again in a moment.";
  }

  if (
    message.includes("No response received") ||
    message.includes("Connection lost before receiving a response")
  ) {
    return "❌ Connection lost before receiving a response. Please try again.";
  }

  if (
    message.includes("AI is taking longer than expected") ||
    message.includes("AI is processing your request")
  ) {
    return "⏳ Your request is taking longer than usual. Try a simpler question or wait a moment and try again.";
  }

  if (message.includes("ECONNREFUSED") || message.includes("ETIMEDOUT")) {
    return "🔌 The GAIA backend is unavailable. Please try again in a moment.";
  }

  if (
    message.includes("Connection interrupted") ||
    message.includes("ECONNRESET") ||
    message.includes("socket hang up") ||
    // Node's premature-close error, raised verbatim as `aborted` when a proxy
    // hangs up mid-response.
    message === "aborted"
  ) {
    return "🔌 Connection interrupted. Please try again.";
  }

  if (message.includes("Stream processing incomplete")) {
    return "⚠️ Response was incomplete. Please try again.";
  }

  return "❌ Something went wrong. Please try again later.";
}
