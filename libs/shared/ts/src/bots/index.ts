/**
 * @module @gaia/shared/bots
 *
 * Shared bot library for all GAIA platform integrations (Discord, Slack, Telegram): adapter/
 * (BaseBotAdapter + renderer), commands/ (unified BotCommand definitions), types/, api/
 * (GaiaClient), config/ (env loader), and utils/ (formatters, command handlers, streaming).
 *
 * New command: add it under commands/<name>.ts and to the allCommands array in commands/index.ts.
 * New platform bot: extend BaseBotAdapter under apps/bots/<platform>/ and call adapter.boot(allCommands).
 */

export type { ActiveBotConversation } from "../api/generated";
export {
  BaseBotAdapter,
  BotServer,
  type OutboundFile,
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
  outboundAttachmentSchemaFor,
  outboundMessageEnvelopeSchemaFor,
} from "./consumer/envelope";
export type {
  ConversationEventSource,
  ConversationSurface,
  DeliveryCursor,
  DeliveryRecorder,
  FollowStart,
  FollowSurface,
  ReplyFile,
  SentBubble,
  StreamingOptions,
} from "./conversation";
export {
  ConversationFollower,
  ConversationFollowers,
  STREAMING_DEFAULTS,
} from "./conversation";
export type {
  DeliveryFailure,
  ReportDeliveryFailure,
} from "./delivery-failures";
export {
  createDeliveryFailureReporter,
  DELIVERY_FAILURE_KIND,
  describeErrorForAlert,
  isLostReply,
} from "./delivery-failures";
export {
  buildLinkCodeFailureMessage,
  consumeInboundLinkCode,
  LINK_CODE_LENGTH,
  parseTrailingLinkCode,
  redeemLinkCode,
} from "./link-codes";
export type {
  InboundLinkCodeArgs,
  LinkCodeFailure,
  LinkState,
  ParsedLinkCode,
} from "./link-codes.types";
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
  BotIntegrationInfo,
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
  MessageTarget,
  OutboundNotifications,
  PlatformName,
  RichMessage,
  RichMessageTarget,
  SentMessage,
  SettingsResponse,
  UnauthenticatedSettingsResponse,
} from "./types";
export type {
  BotFailureReason,
  BotLogFields,
  BotLogger,
  BotLogLevel,
  BotWideEventFields,
  DeliveryConfig,
  DeliveryEvent,
  DeliveryOp,
  DeliveryState,
  IncomingMedia,
  MediaKind,
  MediaOutcome,
  MessageSlot,
  ReactionOutcome,
  WideEventBoundaryFields,
  WideEventEntry,
} from "./utils";
export {
  BODY_READ_TIMEOUT,
  BODY_TOO_LARGE,
  BOT_FAILURE_REASON,
  BOT_MEDIA_LIMITS,
  BUBBLE_PAUSE_MS,
  buildAuthLinkMessage,
  buildPlanRequiredMessage,
  COMMAND_HELP,
  chunkResponse,
  classifyBotFailure,
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
  initialDeliveryState,
  isTableRow,
  isTableSeparator,
  LIVE_PREVIEW_SHARE,
  MEDIA_READ_TIMEOUT_MS,
  MediaReadTimeoutError,
  mediaKindFromMime,
  OUTBOUND_FILE_LIMITS,
  PLATFORM_LIMITS,
  PLATFORM_MARKDOWN,
  parseTextArgs,
  processBotMedia,
  REACTION_OUTCOME,
  readBodyBounded,
  readBodyBytesBounded,
  readResponseBytesCapped,
  readStreamBytesCapped,
  recordBotFailure,
  renderForPlatform,
  sanitizeErrorForLog,
  sendChunked,
  stepDelivery,
  unfetchableMediaMessage,
  unsupportedMediaMessage,
  WEBHOOK_BODY_READ_TIMEOUT_MS,
  WEBHOOK_MAX_BODY_BYTES,
  WIDE_EVENT_MESSAGE,
  wideLog,
  withTimeout,
  withWideEvent,
} from "./utils";
