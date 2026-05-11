/**
 * Stub for chat-ui — types come from libs/chat-ui/src/types/features/chatApiTypes.ts
 * (the real, shared source of truth). Only the runtime functions are stubbed.
 * Real impl in apps/web/src/features/chat/api/chatApi.ts.
 */
import type { EventSourceMessage } from "@microsoft/fetch-event-source";

import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

export type {
  Conversation,
  ConversationSyncItem,
  ConversationWithMessages,
  FetchConversationsResponse,
  FileUploadResponse,
  GenerateImageResponse,
} from "@/types/features/chatApiTypes";
// Re-export the canonical types so existing consumers
// (`from "@/features/chat/api/chatApi"`) keep working unchanged.
export {
  ConversationSource,
  SystemPurpose,
} from "@/types/features/chatApiTypes";

import type {
  Conversation,
  ConversationSyncItem,
  FetchConversationsResponse,
  FileUploadResponse,
  GenerateImageResponse,
  SystemPurpose,
} from "@/types/features/chatApiTypes";

export const chatApi = {
  fetchConversations: async (
    _page = 1,
    _limit = 20,
  ): Promise<FetchConversationsResponse> => ({
    conversations: [],
    total: 0,
    page: 1,
    limit: 20,
    total_pages: 0,
  }),

  batchSyncConversations: async (
    _conversations: ConversationSyncItem[],
  ): Promise<{
    conversations: (Pick<
      Conversation,
      | "conversation_id"
      | "description"
      | "starred"
      | "is_system_generated"
      | "is_unread"
      | "createdAt"
      | "updatedAt"
    > & {
      system_purpose?: SystemPurpose;
      messages: MessageType[];
    })[];
  }> => ({ conversations: [] }),

  uploadFile: async (_file: File): Promise<FileUploadResponse> => ({
    fileId: "",
    fileName: "",
    fileSize: 0,
    contentType: "",
  }),

  generateImage: async (_prompt: string): Promise<GenerateImageResponse> => ({
    url: "",
  }),

  togglePinMessage: async (
    _conversationId: string,
    _messageId: string,
    _pinned: boolean,
  ): Promise<void> => {},

  fetchMessages: async (_conversationId: string): Promise<MessageType[]> => [],

  toggleStarConversation: async (
    _conversationId: string,
    _starred: boolean,
  ): Promise<void> => {},

  deleteConversation: async (_conversationId: string): Promise<void> => {},

  deleteAllConversations: async (): Promise<void> => {},

  renameConversation: async (
    _conversationId: string,
    _title: string,
  ): Promise<void> => {},

  markAsRead: async (_conversationId: string): Promise<void> => {},

  markAsUnread: async (_conversationId: string): Promise<void> => {},

  fetchChatStream: async (
    _inputText: string,
    _convoMessages: MessageType[],
    _conversationId: string | null | undefined,
    _onMessage: (
      event: EventSourceMessage,
    ) => undefined | string | Promise<undefined | string>,
    _onClose: () => void,
    _onError: (err: Error) => void,
    _fileData: FileData[] = [],
    _selectedTool: string | null = null,
    _toolCategory: string | null = null,
    _externalController?: AbortController,
    _selectedWorkflow: WorkflowData | null = null,
    _selectedCalendarEvent: SelectedCalendarEventData | null = null,
    _replyToMessage: {
      id: string;
      content: string;
      role: "user" | "assistant";
    } | null = null,
  ): Promise<void> => {},
};
