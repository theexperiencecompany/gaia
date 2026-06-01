/**
 * Pure display formatters for bot responses.
 *
 * These are data-in, string-out functions with no side effects.
 * They are used by the shared command handlers in commands.ts
 * and can also be called directly when assembling custom responses.
 *
 * formatBotError is the single error formatter for all bots.
 * It checks for GaiaApiError (preserves HTTP status), then
 * falls back to axios-style errors, then generic Error messages.
 */
import { GaiaApiError } from "../api";
import type {
  BotConversation,
  BotTodo,
  BotWorkflow,
  PlatformName,
} from "../types";
import { isTableRow, isTableSeparator } from "./text";

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
 * Escapes the three characters that are special in Telegram HTML body text:
 * `&`, `<`, `>`. Everything else (`_`, `*`, `(`, `)`, `.`, `-`, …) is literal
 * in HTML mode — which is exactly why HTML is immune to the legacy-Markdown
 * breakage where an underscore in a URL or a snake_case token gets parsed as
 * an emphasis marker.
 *
 * Slack's mrkdwn control-character escaping happens to require the same three
 * entities, so {@link convertToSlackMrkdwn} reuses this helper.
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
  for (let i = 0; i < lines.length; i += 1) {
    const header = lines[i] ?? "";
    if (isTableRow(header) && isTableSeparator(lines[i + 1] ?? "")) {
      const block = [header, lines[i + 1] ?? ""];
      let j = i + 2;
      while (j < lines.length && isTableRow(lines[j] ?? "")) {
        block.push(lines[j] ?? "");
        j += 1;
      }
      out.push(hold(renderTelegramTable(block.join("\n"))));
      i = j - 1;
    } else {
      out.push(header);
    }
  }
  return out.join("\n");
}

/**
 * Converts the CommonMark the agent emits for Telegram into Telegram's **HTML**
 * parse mode (https://core.telegram.org/bots/api#html-style).
 *
 * HTML is used instead of legacy `Markdown`/`MarkdownV2` because it is the only
 * mode where URLs and prose never collide with formatting markers: the sole
 * special characters are `&`, `<`, `>`, so underscores in tokens/URLs,
 * snake_case identifiers and stray `*` can never trigger a parse error or eat
 * characters. (Legacy Markdown italicized `..._x_...` inside auth-token URLs and
 * silently dropped the underscores — see the formatter tests.)
 *
 * Strategy: pull code spans, code blocks and links out into placeholders so
 * their contents are never treated as markup, HTML-escape the remaining
 * narrative, translate the markdown that survives into Telegram tags, then
 * splice the placeholders back in. Telegram HTML has no heading or list tags,
 * so headings become bold and bullets become `•`.
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
    .replaceAll(/^&gt;[ \t]?/gm, "") // blockquote → strip marker
    .replaceAll(/^[-_]{3,}$/gm, "") // horizontal rule → remove
    // Inline emphasis. Bold before italic so `**` is consumed first.
    .replaceAll(/\*\*\*([^*\n]+?)\*\*\*/g, "<b><i>$1</i></b>") // ***x***
    .replaceAll(/\*\*([^*\n]+?)\*\*/g, "<b>$1</b>") // **x**
    .replaceAll(/__([^_\n]+?)__/g, "<b>$1</b>") // __x__
    .replaceAll(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, "<i>$1</i>") // *x*
    .replaceAll(/(?<!\w)_([^_\n]+?)_(?!\w)/g, "<i>$1</i>") // _x_ (skips snake_case)
    .replaceAll(/~~([^~\n]+?)~~/g, "<s>$1</s>"); // ~~x~~

  // Resolve placeholders, looping so a stashed table that contains a stashed
  // link (a nested placeholder) is fully spliced back in. Loop only while a
  // real placeholder token remains AND each pass makes progress, so a stray
  // U+E000 in the source text (not a valid \uE000<index>\uE000 token) can never
  // spin the loop forever and wedge the bot's event loop.
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
 * Converts standard CommonMark Markdown to Slack mrkdwn.
 *
 * Slack mrkdwn supports: `*bold*`, `_italic_`, `~strike~`, `` `code` ``,
 * ` ```code``` `, `<url|label>` hyperlinks.
 *
 * Converts `**bold**` → `*bold*`, `~~strike~~` → `~strike~`,
 * `[label](url)` → `<url|label>`, strips `# headers` to bold, strips
 * blockquote `>` prefixes and horizontal rules. Crucially it also escapes the
 * three Slack control characters (`&`, `<`, `>`) in narrative text so a stray
 * `<` no longer makes Slack swallow the rest of the line as a broken link.
 * Link `<url|label>` sequences and fenced code blocks are protected from that
 * escaping. (Underscores and `*` are literal in mrkdwn, so they need no
 * escaping — only the angle-bracket/ampersand trio does.)
 */
export function convertToSlackMrkdwn(text: string): string {
  return applyOutsideCodeBlocks(text, (segment) => {
    // Stash link control-sequences so the escape pass below cannot mangle the
    // URL or the `<url|label>` angle brackets. U+E000 sentinels never occur in
    // real text and survive escaping untouched.
    const stash: string[] = [];
    const hold = (mrkdwn: string): string => {
      stash.push(mrkdwn);
      return `\uE000${stash.length - 1}\uE000`;
    };
    const converted = segment
      // Masked links → <url|label>. Only the label (display text) is escaped;
      // the URL is left verbatim, as Slack expects inside the angle brackets.
      .replaceAll(
        /\[([^\]\n]{1,500})\]\(([^)\s]{1,2048})\)/g,
        (_m, label, url) => hold(`<${url}|${escapeHtml(label as string)}>`),
      )
      .replaceAll(/\*\*\*([^*\n]+?)\*\*\*/g, "*$1*") // ***bold italic*** → *bold*
      .replaceAll(/\*\*([^*\n]+?)\*\*/g, "*$1*") // **bold** → *bold*
      .replaceAll(/~~([^~\n]+?)~~/g, "~$1~") // ~~strike~~ → ~strike~
      .replaceAll(/^#{1,6}[ \t]+(.+)$/gm, "*$1*") // # Heading → *Heading*
      .replaceAll(/^>[ \t]*/gm, "") // > quote → strip prefix (before escaping)
      .replaceAll(/^[-_]{3,}$/gm, ""); // --- / ___ → remove
    // Escape Slack control chars in surviving narrative, then restore links.
    return escapeHtml(converted).replaceAll(
      /\uE000(\d+)\uE000/g,
      (_m, i) => stash[Number(i)],
    );
  });
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
        // Headings FIRST so the content gets wrapped in ``*`` before the
        // bold rule sees it. Otherwise the model's ``### **Heading**`` would
        // become ``### *Heading*`` (after bold) and then ``**Heading**`` once
        // the heading rule wraps the already-emphasised content in ``*`` —
        // re-introducing the double asterisks we tried to remove.
        .replaceAll(/^#{1,6}\s+(.+)$/gm, "*$1*") // # Heading → *Heading*
        // Horizontal-rule remover MUST run before the bold rule. Otherwise
        // ``***`` on its own line followed by ``**Heading**`` lets the bold
        // regex's ``[^*]`` greedy-match the inter-line newlines and pair
        // chars across the ``***`` boundary into ``**X**``, splitting the
        // ``**Heading**`` and leaving stray ``**`` glyphs in the output.
        .replaceAll(/^[-_*]{3,}$/gm, "") // --- / ___ / *** → remove
        // Bold rules: keep ``[^*\n]`` (no newlines) so a single ``**`` opener
        // cannot reach across blank lines and accidentally pair with the
        // opener of a SEPARATE bold span.
        .replaceAll(/\*\*\*([^*\n]+)\*\*\*/g, "*$1*") // ***bold italic*** → *bold*
        .replaceAll(/\*\*([^*\n]+)\*\*/g, "*$1*") // **bold** → *bold*
        .replaceAll(/\[([^\]]{1,500})\]\(([^)]{1,2048})\)/g, "$1 ($2)") // [label](url) → label (url)
        .replaceAll(/^(\s*)[*\-+]\s+/gm, "$1• ") // - / * / + bullet → •
        .replaceAll(/^>\s*/gm, ""), // > quote → strip prefix
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
 * The single canonical "link your account" prompt.
 *
 * Used BOTH by the `/auth` command and by every adapter's streaming
 * `onAuthError` path, on all four platforms — so an unlinked user sees the
 * exact same message whether they type `/auth` or just send "hi". Previously
 * each adapter hardcoded its own divergent copy, which is the inconsistency
 * this removes.
 *
 * The URL is shown **bare** (not a masked link) on purpose: a bare URL stays
 * visible and copy-pasteable, and every platform auto-links it once it points
 * at a real public domain (the production `GAIA_FRONTEND_URL`). A masked
 * `[label](url)` would hide the URL, and Telegram refuses to linkify or accept
 * `<a href>` entities for non-public hosts like `localhost`, so in dev it would
 * render as dead plain text with no URL at all.
 *
 * Callers still send it through `renderForPlatform` (and `parse_mode: HTML` on
 * Telegram) so the `**bold**` heading renders consistently.
 */
export function buildAuthLinkMessage(authUrl: string): string {
  return (
    "🔗 **Link your account to GAIA**\n\n" +
    "Tap the link below to sign in and link your account:\n" +
    `${authUrl}\n\n` +
    "After linking, you'll be able to use all GAIA commands!"
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
 * Formats an error message for user display.
 */
export function formatBotError(error: unknown): string {
  const status =
    error instanceof GaiaApiError
      ? error.status
      : (error as { response?: { status?: number } })?.response?.status;

  if (status === 401) {
    return "❌ Authentication required. Use `/auth` to link your account.";
  }

  if (status === 404) {
    return "❌ Not found. Please check the ID and try again.";
  }

  if (status === 429) {
    return "⏳ You're sending messages too fast. Please wait a moment and try again.";
  }

  const message = error instanceof Error ? error.message : String(error ?? "");

  if (message.includes("timed out") || message.includes("timeout")) {
    return "⏳ The request timed out. The server may be busy — please try again in a moment.";
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
    message.includes("socket hang up")
  ) {
    return "🔌 Connection interrupted. Please try again.";
  }

  if (message.includes("Stream processing incomplete")) {
    return "⚠️ Response was incomplete. Please try again.";
  }

  console.error("Unhandled bot error:", error);
  return "❌ Something went wrong. Please try again later.";
}
