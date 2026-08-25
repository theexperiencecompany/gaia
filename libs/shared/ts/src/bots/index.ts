/**
 * @module @gaia/shared/bots
 *
 * Shared bot library for all GAIA platform integrations (Discord, Slack, Telegram).
 *
 * Architecture overview:
 * - adapter/   - BaseBotAdapter abstract class + richMessageToMarkdown renderer
 * - commands/  - Unified BotCommand definitions (auth, help, settings, gaia, todo, etc.)
 * - types/     - Shared TypeScript interfaces (ChatRequest, CommandContext, BotCommand, etc.)
 * - api/       - GaiaClient: single HTTP client for all bot-to-backend communication
 * - config/    - Environment variable loader (GAIA_API_URL, GAIA_BOT_API_KEY, etc.)
 * - utils/     - Reusable logic split into three layers:
 *     - formatters.ts  - Pure display functions (formatTodo, formatBotError, etc.)
 *     - commands.ts    - Business-logic handlers (handleTodoList, dispatchTodoSubcommand, etc.)
 *     - streaming.ts   - handleStreamingChat: shared streaming + throttled editing
 *
 * When adding a new bot command:
 * 1. Create a new BotCommand in commands/<name>.ts
 * 2. Add it to the allCommands array in commands/index.ts
 * 3. If needed, add API methods to GaiaClient and formatters to formatters.ts
 *
 * When adding a new platform bot:
 * 1. Create a new directory under apps/bots/<platform>/
 * 2. Extend BaseBotAdapter and implement the five lifecycle methods
 * 3. In index.ts: create adapter instance, call adapter.boot(allCommands)
 */
export {
  BaseBotAdapter,
  BotServer,
  richMessageToMarkdown,
  runBotProcess,
} from "./adapter";

export { GaiaApiError, GaiaClient } from "./api";
export {
  allCommands,
  authCommand,
  conversationsCommand,
  gaiaCommand,
  helpCommand,
  newCommand,
  settingsCommand,
  statusCommand,
  stopCommand,
  todoCommand,
  unlinkCommand,
  workflowCommand,
} from "./commands";
export { injectInfisicalSecrets, loadConfig } from "./config";
// Outbound envelope types/schema (zod-only — RN-safe). The full consumer
// (`./consumer/outbound-consumer`) is NOT re-exported here: it imports amqplib
// (Node-only), which Metro/React Native cannot resolve.
export type {
  OutboundAttachment,
  OutboundMessageEnvelope,
} from "./consumer/envelope";

export {
  outboundAttachmentSchema,
  outboundMessageEnvelopeSchema,
} from "./consumer/envelope";
export type {
  AuthenticatedSettingsResponse,
  AuthStatus,
  BotCommand,
  BotCommandOption,
  BotConfig,
  BotConversation,
  BotConversationListResponse,
  BotCreateTodoRequest,
  BotFileData,
  BotSubcommand,
  BotTodo,
  BotTodoListResponse,
  BotUserContext,
  BotWorkflow,
  BotWorkflowExecutionRequest,
  BotWorkflowExecutionResponse,
  BotWorkflowListResponse,
  ChatRequest,
  CommandContext,
  CommandExecuteParams,
  IntegrationInfo,
  MessageTarget,
  PlatformName,
  RichMessage,
  RichMessageTarget,
  SentMessage,
  SettingsResponse,
  UnauthenticatedSettingsResponse,
} from "./types";
export type {
  BotLogFields,
  BotLogger,
  BotLogLevel,
  BotWideEventFields,
  IncomingMedia,
  MediaKind,
  MediaOutcome,
  MessageEditor,
  NewMessageSender,
  StreamingOptions,
  WideEventBoundaryFields,
  WideEventEntry,
} from "./utils";
export {
  BODY_READ_TIMEOUT,
  BODY_TOO_LARGE,
  BOT_MEDIA_LIMITS,
  buildAuthLinkMessage,
  buildPlanRequiredMessage,
  COMMAND_HELP,
  chunkResponse,
  convertToDiscordMarkdown,
  convertToImessageText,
  convertToSlackMrkdwn,
  convertToTelegramHtml,
  convertToWhatsAppMarkdown,
  createBotLogger,
  dispatchTodoSubcommand,
  dispatchWorkflowSubcommand,
  emitBotLogLine,
  escapeHtml,
  escapeHtmlAttr,
  extensionForMime,
  extractSubcommandArgs,
  fetchBytesCapped,
  formatBotError,
  formatConversation,
  formatConversationList,
  formatTodo,
  formatTodoList,
  formatWorkflow,
  formatWorkflowList,
  friendlyMediaError,
  getHttpStatus,
  handleConversationList,
  handleNewConversation,
  handleStreamingChat,
  handleTodoComplete,
  handleTodoCreate,
  handleTodoDelete,
  handleTodoList,
  handleWorkflowCreate,
  handleWorkflowDelete,
  handleWorkflowExecute,
  handleWorkflowGet,
  handleWorkflowList,
  hashLogIdentifier,
  htmlToPlainText,
  isTableRow,
  isTableSeparator,
  MEDIA_READ_TIMEOUT_MS,
  MediaReadTimeoutError,
  mediaKindFromMime,
  OUTBOUND_FILE_LIMITS,
  PLATFORM_LIMITS,
  PLATFORM_MARKDOWN,
  parseTextArgs,
  processBotMedia,
  readBodyBounded,
  readBodyBytesBounded,
  readResponseBytesCapped,
  readStreamBytesCapped,
  renderForPlatform,
  STREAMING_DEFAULTS,
  sanitizeErrorForLog,
  segmentIntoBubbles,
  sendChunked,
  unfetchableMediaMessage,
  unsupportedMediaMessage,
  WEBHOOK_BODY_READ_TIMEOUT_MS,
  WEBHOOK_MAX_BODY_BYTES,
  WIDE_EVENT_MESSAGE,
  wideLog,
  withWideEvent,
} from "./utils";
