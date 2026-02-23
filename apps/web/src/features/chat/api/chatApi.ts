import {
  type EventSourceMessage,
  fetchEventSource,
} from "@microsoft/fetch-event-source";

import { apiService } from "@/lib/api";
import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared";

export interface FileUploadResponse {
  fileId: string;
  fileName: string;
  fileSize: number;
  contentType: string;
  url?: string;
  description?: string;
  message?: string;
}

export interface GenerateImageResponse {
  url: string;
  improved_prompt?: string;
}

export enum SystemPurpose {
  EMAIL_PROCESSING = "email_processing",
  WORKFLOW_EXECUTION = "workflow_execution",
  OTHER = "other", // Add more purposes as needed
}

export enum ConversationSource {
  WEB = "web",
  MOBILE = "mobile",
  TELEGRAM = "telegram",
  DISCORD = "discord",
  SLACK = "slack",
  WHATSAPP = "whatsapp",
  WORKFLOW_SYSTEM = "workflow_system",
}

export interface Conversation {
  _id: string;
  user_id: string;
  conversation_id: string;
  description: string;
  starred?: boolean;
  is_system_generated?: boolean;
  system_purpose?: SystemPurpose;
  is_unread?: boolean;
  source?: ConversationSource;
  createdAt: string;
  updatedAt?: string;
}

export interface ConversationWithMessages {
  id: string;
  title: string;
  messages: MessageType[];
}

export interface FetchConversationsResponse {
  conversations: Conversation[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface ConversationSyncItem {
  conversation_id: string;
  last_updated?: string;
}

export const chatApi = {
  // Fetch conversations with pagination
  fetchConversations: async (
    page = 1,
    limit = 20,
  ): Promise<FetchConversationsResponse> => {
    return apiService.get<FetchConversationsResponse>(
      `/conversations?page=${page}&limit=${limit}`,
      {
        errorMessage: "Failed to fetch conversations",
      },
    );
  },

  // Batch sync conversations - only fetch stale conversations
  batchSyncConversations: async (
    conversations: ConversationSyncItem[],
  ): Promise<{
    conversations: {
      conversation_id: string;
      description: string;
      starred?: boolean;
      is_system_generated?: boolean;
      system_purpose?: SystemPurpose;
      is_unread?: boolean;
      createdAt: string;
      updatedAt?: string;
      messages: MessageType[];
    }[];
  }> => {
    return apiService.post(
      "/conversations/batch-sync",
      { conversations },
      {
        errorMessage: "Failed to sync conversations",
        silent: true,
      },
    );
  },

  // File upload
  uploadFile: async (file: File): Promise<FileUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);

    return apiService.post<FileUploadResponse>("/upload", formData, {
      errorMessage: "Failed to upload file",
    });
  },

  // Generate image
  generateImage: async (prompt: string): Promise<GenerateImageResponse> => {
    return apiService.post<GenerateImageResponse>(
      "/image/generate",
      { message: prompt },
      {
        successMessage: "Image generated successfully",
        errorMessage: "Failed to generate image",
      },
    );
  },

  // Pin/unpin message
  togglePinMessage: async (
    conversationId: string,
    messageId: string,
    pinned: boolean,
  ): Promise<void> => {
    return apiService.put(
      `/conversations/${conversationId}/messages/${messageId}/pin`,
      { pinned },
      {
        successMessage: pinned ? "Message pinned" : "Message unpinned",
        errorMessage: `Failed to ${pinned ? "pin" : "unpin"} message`,
      },
    );
  },

  // Fetch messages for a conversation
  fetchMessages: async (conversationId: string): Promise<MessageType[]> => {
    const response = await apiService.get<ConversationWithMessages>(
      `/conversations/${conversationId}`,
      {
        errorMessage: "Failed to fetch messages",
      },
    );
    return response.messages;
  },

  // Star/unstar conversation
  toggleStarConversation: async (
    conversationId: string,
    starred: boolean,
  ): Promise<void> => {
    return apiService.put(
      `/conversations/${conversationId}/star`,
      { starred },
      {
        successMessage: starred
          ? "Conversation starred"
          : "Conversation unstarred",
        errorMessage: `Failed to ${starred ? "star" : "unstar"} conversation`,
      },
    );
  },

  // Delete conversation
  deleteConversation: async (conversationId: string): Promise<void> => {
    return apiService.delete(`/conversations/${conversationId}`, {
      successMessage: "Conversation deleted",
      errorMessage: "Failed to delete conversation",
    });
  },

  // Delete all conversations
  deleteAllConversations: async (): Promise<void> => {
    return apiService.delete("/conversations", {
      successMessage: "All conversations deleted",
      errorMessage: "Failed to delete conversations",
    });
  },

  // Rename conversation
  renameConversation: async (
    conversationId: string,
    title: string,
  ): Promise<void> => {
    return apiService.put(
      `/conversations/${conversationId}/description`,
      { description: title },
      {
        successMessage: "Conversation renamed",
        errorMessage: "Failed to rename conversation",
      },
    );
  },

  // Mark conversation as read
  markAsRead: async (conversationId: string): Promise<void> => {
    return apiService.patch(`/conversations/${conversationId}/read`, {});
  },

  // Mark conversation as unread
  markAsUnread: async (conversationId: string): Promise<void> => {
    return apiService.patch(`/conversations/${conversationId}/unread`, {});
  },

  // Fetch chat stream
  fetchChatStream: async (
    inputText: string,
    convoMessages: MessageType[],
    conversationId: string | null | undefined,
    onMessage: (
      event: EventSourceMessage,
    ) => undefined | string | Promise<undefined | string>,
    onClose: () => void,
    onError: (err: Error) => void,
    fileData: FileData[] = [],
    selectedTool: string | null = null,
    toolCategory: string | null = null,
    externalController?: AbortController,
    selectedWorkflow: WorkflowData | null = null,
    selectedCalendarEvent: SelectedCalendarEventData | null = null,
    replyToMessage: {
      id: string;
      content: string;
      role: "user" | "assistant";
    } | null = null,
  ) => {
    const controller = externalController || new AbortController();
    // Extract fileIds from fileData for backward compatibility
    const fileIds = fileData.map((file) => file.fileId);

    // If conversationId is not provided, try to extract it from the URL
    if (conversationId === undefined && typeof window !== "undefined") {
      const match = window.location.pathname.match(/\/c\/([^/]+)(?:\/|$)/);
      if (match) conversationId = match[1];
    }

    await fetchEventSource(
      `${process.env.NEXT_PUBLIC_API_BASE_URL}chat-stream`,
      {
        openWhenHidden: true,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          "x-timezone": Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
        credentials: "include",
        signal: controller.signal,
        body: JSON.stringify({
          conversation_id: conversationId || null,
          message: inputText,
          fileIds, // For backward compatibility
          fileData, // Send complete file data
          selectedTool, // Add selectedTool to the request body
          toolCategory, // Add toolCategory to the request body
          selectedWorkflow, // Add selectedWorkflow to the request body
          selectedCalendarEvent, // Add selectedCalendarEvent to the request body
          replyToMessage, // Add replyToMessage to the request body
          messages: convoMessages
            .slice(-30)
            .filter(({ response }) => response.trim().length > 0)
            .map(({ type, response }, _index, _array) => ({
              role: type === "bot" ? "assistant" : type,
              content: response,
            })),
        }),

        onmessage(event) {
          const errorResult = onMessage(event);

          if (event.data === "[DONE]") {
            onClose();
            return;
          }

          // Handle both sync and async error returns
          if (errorResult) {
            if (errorResult instanceof Promise) {
              errorResult.then((err) => {
                if (err) {
                  console.error(
                    "[chatApi] Message handler returned async error:",
                    err,
                  );
                  onError(new Error(err));
                  controller.abort();
                }
              });
            } else {
              console.error(
                "[chatApi] Message handler returned error:",
                errorResult,
              );
              onError(new Error(errorResult));
              controller.abort();
            }
            return;
          }
        },
        onclose() {
          onClose();
        },
        onerror: (err) => {
          console.error("[chatApi] Stream error:", {
            error: err,
            message: err.message,
            stack: err.stack,
          });
          onError(err);
          throw err; // This stops any retry attempts
        },
      },
    );
  },
};
