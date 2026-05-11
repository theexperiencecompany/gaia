// @heygaia/chat-ui — public API.
// All exports from the GAIA chat feature, extracted so they can be reused
// across surfaces (web app, motion studio, demos).

// === Tool registries ===
export * from "./config/registries/toolRegistry";
export { default as ChatBubbleBot } from "./features/chat/components/bubbles/bot/ChatBubbleBot";
export { default as FollowUpActions } from "./features/chat/components/bubbles/bot/FollowUpActions";
export { default as ImageBubble } from "./features/chat/components/bubbles/bot/ImageBubble";
export { default as TextBubble } from "./features/chat/components/bubbles/bot/TextBubble";
export { default as ThinkingBubble } from "./features/chat/components/bubbles/bot/ThinkingBubble";
export { default as ToolCallsSection } from "./features/chat/components/bubbles/bot/ToolCallsSection";
// === Core chat bubbles ===
export { default as ChatBubbleUser } from "./features/chat/components/bubbles/user/ChatBubbleUser";
export { default as ChatRenderer } from "./features/chat/components/interface/ChatRenderer";
// === Interface ===
export { LoadingIndicator } from "./features/chat/components/interface/LoadingIndicator";
export { default as MarkdownRenderer } from "./features/chat/components/interface/MarkdownRenderer";
export type * from "./types/features/baseMessageTypes";
export type {
  Conversation,
  ConversationSyncItem,
  ConversationWithMessages,
  FetchConversationsResponse,
  FileUploadResponse,
  GenerateImageResponse,
} from "./types/features/chatApiTypes";
// Canonical chatApi types (shared between this package's stubs and apps/web's
// real impl) — single source of truth, no drift.
export {
  ConversationSource,
  SystemPurpose,
} from "./types/features/chatApiTypes";
// === Types ===
export type {
  ChatBubbleBotProps,
  ChatBubbleUserProps,
} from "./types/features/chatBubbleTypes";
export type * from "./types/features/convoTypes";
export type * from "./types/features/toolDataTypes";
