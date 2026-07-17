/**
 * Bot utility barrel export.
 *
 * Three layers of reusable logic, ordered from low-level to high-level:
 *
 * 1. formatters - Pure functions that turn data into display strings.
 *    Use these when you need custom response assembly.
 *
 * 2. commands  - Business-logic handlers that call GaiaClient, format results,
 *    and return a ready-to-send string. Bot adapters call these directly.
 *
 * 3. streaming - handleStreamingChat: full streaming lifecycle handler.
 *    Bot adapters provide three callbacks (editMessage, onAuthError, onGenericError)
 *    and the shared function handles throttling, cursor display, and error routing.
 *
 * Text helpers (arg parsing, platform limits, truncation, chunking) live in
 * ./text so sibling modules can import them without a barrel import cycle.
 */

export {
  dispatchTodoSubcommand,
  dispatchWorkflowSubcommand,
  handleConversationList,
  handleNewConversation,
  handleTodoComplete,
  handleTodoCreate,
  handleTodoDelete,
  handleTodoList,
  handleWorkflowCreate,
  handleWorkflowDelete,
  handleWorkflowExecute,
  handleWorkflowGet,
  handleWorkflowList,
} from "./commands";
export {
  buildAuthLinkMessage,
  COMMAND_HELP,
  convertToDiscordMarkdown,
  convertToSlackMrkdwn,
  convertToTelegramHtml,
  convertToWhatsAppMarkdown,
  escapeHtml,
  escapeHtmlAttr,
  formatBotError,
  formatConversation,
  formatConversationList,
  formatTodo,
  formatTodoList,
  formatWorkflow,
  formatWorkflowList,
  htmlToPlainText,
  PLATFORM_MARKDOWN,
  renderForPlatform,
} from "./formatters";
export {
  type BotLogFields,
  type BotLogger,
  createBotLogger,
  getHttpStatus,
  hashLogIdentifier,
  sanitizeErrorForLog,
} from "./logger";
export {
  BOT_MEDIA_LIMITS,
  extensionForMime,
  friendlyMediaError,
  type IncomingMedia,
  type MediaKind,
  type MediaOutcome,
  mediaKindFromMime,
  OUTBOUND_FILE_LIMITS,
  processBotMedia,
  unsupportedMediaMessage,
} from "./media";
export {
  handleStreamingChat,
  type MessageEditor,
  type NewMessageSender,
  STREAMING_DEFAULTS,
  type StreamingOptions,
} from "./streaming";
export {
  chunkResponse,
  extractSubcommandArgs,
  isTableRow,
  isTableSeparator,
  PLATFORM_LIMITS,
  parseTextArgs,
  truncateResponse,
} from "./text";
