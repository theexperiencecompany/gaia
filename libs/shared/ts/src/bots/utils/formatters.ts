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
import type { BotConversation, BotTodo, BotWorkflow } from "../types";

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
 * Converts standard CommonMark Markdown to Telegram legacy Markdown.
 *
 * Telegram's legacy `Markdown` parse mode supports:
 * `*bold*`, `_italic_`, `` `code` ``, ` ```code``` `, `[text](url)`.
 *
 * Converts `**bold**` → `*bold*`, strips unsupported `# headers` to bold,
 * and removes blockquote `>` prefixes and horizontal rules.
 * Code blocks are preserved unchanged.
 */
export function convertToTelegramMarkdown(text: string): string {
  return applyOutsideCodeBlocks(
    text,
    (segment) =>
      segment
        .replace(/\*\*\*(.+?)\*\*\*/g, "*$1*") // ***bold italic*** → *bold*
        .replace(/\*\*(.+?)\*\*/g, "*$1*") // **bold** → *bold*
        .replace(/^#{1,6}\s+(.+)$/gm, "*$1*") // # Heading → *Heading*
        .replace(/^>\s*/gm, "") // > quote → strip prefix
        .replace(/^[-_]{3,}$/gm, ""), // --- / ___ → remove
  );
}

/**
 * Converts standard CommonMark Markdown to Slack mrkdwn.
 *
 * Slack mrkdwn supports: `*bold*`, `_italic_`, `` `code` ``, ` ```code``` `,
 * `<url|label>` hyperlinks.
 *
 * Converts `**bold**` → `*bold*`, `[label](url)` → `<url|label>`,
 * strips `# headers` to bold, strips blockquote `>` prefixes and horizontal rules.
 * Code blocks are preserved unchanged.
 */
export function convertToSlackMrkdwn(text: string): string {
  return applyOutsideCodeBlocks(
    text,
    (segment) =>
      segment
        .replace(/\*\*\*(.+?)\*\*\*/g, "*$1*") // ***bold italic*** → *bold*
        .replace(/\*\*(.+?)\*\*/g, "*$1*") // **bold** → *bold*
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "<$2|$1>") // [label](url) → <url|label>
        .replace(/^#{1,6}\s+(.+)$/gm, "*$1*") // # Heading → *Heading*
        .replace(/^>\s*/gm, "") // > quote → strip prefix
        .replace(/^[-_]{3,}$/gm, ""), // --- / ___ → remove
  );
}

/**
 * Formats authentication required message with clear onboarding steps.
 */
export function formatAuthRequiredMessage(
  platform: string,
  authUrl: string,
  context?: string,
): string {
  const platformName = platform.charAt(0).toUpperCase() + platform.slice(1);

  return (
    `🔐 **Authentication Required**\n\n` +
    `To ${context || "use this feature"}, link your ${platformName} account to GAIA.\n\n` +
    `**Steps:**\n` +
    `1. Click: ${authUrl}\n` +
    `2. Sign in to GAIA (or create account)\n` +
    `3. Confirm connection\n` +
    `4. Return and try again!\n\n` +
    `Need help? Use /help`
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
