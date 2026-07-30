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
export type { BotLogFields, BotLogger, BotLogLevel } from "./logger";
export {
  createBotLogger,
  emitBotLogLine,
  getHttpStatus,
  hashLogIdentifier,
  sanitizeErrorForLog,
} from "./logger";
export type { IncomingMedia, MediaKind, MediaOutcome } from "./media";
export {
  BOT_MEDIA_LIMITS,
  extensionForMime,
  friendlyMediaError,
  mediaKindFromMime,
  OUTBOUND_FILE_LIMITS,
  processBotMedia,
  unsupportedMediaMessage,
} from "./media";
export type {
  MessageEditor,
  NewMessageSender,
  StreamingOptions,
} from "./streaming";
export { handleStreamingChat, STREAMING_DEFAULTS } from "./streaming";
export {
  chunkResponse,
  extractSubcommandArgs,
  isTableRow,
  isTableSeparator,
  PLATFORM_LIMITS,
  parseTextArgs,
  truncateResponse,
} from "./text";
export type {
  BotWideEventFields,
  WideEventBoundaryFields,
  WideEventEntry,
} from "./wide-events";
export { WIDE_EVENT_MESSAGE, wideLog, withWideEvent } from "./wide-events";
