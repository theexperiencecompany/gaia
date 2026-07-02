import {
  type EventSourceMessage,
  fetchEventSource,
} from "@microsoft/fetch-event-source";

import type { DesktopToolResult } from "@shared/desktop-tools";
import { apiService } from "@/lib/api/service";
import { desktopClientHeaders } from "@/lib/electron/api";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import { getBrowserTimezone } from "@/lib/timezone";
import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import { useComposerStore } from "@/stores/composerStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

/** Thrown when the backend rejects a send whose turn_id was already claimed —
 *  the original request is (or was) processing; the retry must not re-run. */
export class DuplicateTurnError extends Error {
  constructor() {
    super("This send was already accepted by the server");
    this.name = "DuplicateTurnError";
  }
}

const HTTP_CONFLICT = 409;

export interface ChatStreamRequest {
  inputText: string;
  /** Prior turns as role/content pairs — the caller owns history assembly. */
  history: { role: "user" | "assistant"; content: string }[];
  /** Target conversation; null asks the backend to create one. */
  conversationId: string | null;
  /** Client id for this SEND, stable across retries — backend dedup key. */
  turnId: string | null;
  onMessage: (
    event: EventSourceMessage,
  ) => undefined | string | Promise<undefined | string>;
  onClose: () => void;
  onError: (err: Error) => void;
  controller: AbortController;
  fileData: FileData[];
  selectedTool: string | null;
  toolCategory: string | null;
  selectedWorkflow: WorkflowData | null;
  selectedCalendarEvent: SelectedCalendarEventData | null;
  replyToMessage: {
    id: string;
    content: string;
    role: "user" | "assistant";
  } | null;
  isOnboardingDemo: boolean;
}

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
  DESKTOP = "desktop",
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
  is_onboarding_conversation?: boolean;
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
      is_onboarding_conversation?: boolean;
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

    // No errorMessage override: let the backend detail surface (e.g. the 413
    // "File size exceeds the N MB limit." or 415 unsupported-type message)
    // instead of masking it with a generic "Failed to upload file".
    return apiService.post<FileUploadResponse>("/upload", formData);
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

  // Submit thumbs-up / thumbs-down feedback for an assistant message.
  // Lands as a Langfuse score on the trace deterministically derived from
  // message_id. Best-effort: failures don't surface to the user.
  submitMessageFeedback: async (
    messageId: string,
    isPositive: boolean,
  ): Promise<void> => {
    return apiService.post(
      `/messages/${messageId}/feedback`,
      { is_positive: isPositive },
      {
        silent: true,
        errorMessage: "Failed to record feedback",
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
  fetchChatStream: async (request: ChatStreamRequest) => {
    const {
      inputText,
      history,
      conversationId,
      turnId,
      onMessage,
      onClose,
      onError,
      controller,
      fileData,
      selectedTool,
      toolCategory,
      selectedWorkflow,
      selectedCalendarEvent,
      replyToMessage,
      isOnboardingDemo,
    } = request;

    // Guard against double onClose — [DONE] in onmessage fires onClose, then
    // the SSE library fires onclose when the connection ends.  Without this
    // flag both would call onClose, causing duplicate cleanup / persistence.
    let doneReceived = false;

    // DEV-ONLY: per-request model overrides from the chat-header selector. Read
    // at send time from the composer store. The backend ignores these unless
    // ENV=development; `use_default_models` keeps the plan-routed default.
    const { useDefaultModels, commsModel, executorModel } =
      useComposerStore.getState();

    await fetchEventSource(
      `${process.env.NEXT_PUBLIC_API_BASE_URL}chat-stream`,
      {
        openWhenHidden: true,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          "x-timezone": getBrowserTimezone(),
          ...desktopClientHeaders(),
        },
        credentials: "include",
        signal: controller.signal,
        // Default onopen only validates content-type; a 409 (duplicate turn_id
        // claim) must surface as a typed error so the session can reconcile
        // instead of showing a failure for a send that IS being processed.
        async onopen(response) {
          if (response.status === HTTP_CONFLICT) {
            throw new DuplicateTurnError();
          }
          if (
            !response.ok ||
            !response.headers.get("content-type")?.includes("text/event-stream")
          ) {
            throw new Error(
              `Unexpected chat-stream response (${response.status})`,
            );
          }
        },
        body: JSON.stringify({
          conversation_id: conversationId,
          turn_id: turnId,
          message: inputText,
          fileIds: fileData.map((file) => file.fileId),
          fileData,
          selectedTool,
          toolCategory,
          selectedWorkflow,
          selectedCalendarEvent,
          replyToMessage,
          is_onboarding_demo: isOnboardingDemo,
          use_default_models: useDefaultModels,
          comms_model: useDefaultModels ? null : commsModel,
          executor_model: useDefaultModels ? null : executorModel,
          messages: history.slice(-30),
        }),

        onmessage(event) {
          const errorResult = onMessage(event);

          if (event.data === "[DONE]") {
            doneReceived = true;
            onClose();
            return;
          }

          // onMessage is async — surface errors from the Promise. No queue/gate
          // needed: conversation binding updates the Zustand store synchronously
          // before any awaits, so subsequent events can render immediately.
          if (errorResult instanceof Promise) {
            errorResult.then((err) => {
              if (err) {
                console.error("[chatApi] Stream event error:", err);
                onError(new Error(err));
                controller.abort();
              }
            });
          } else if (errorResult) {
            console.error("[chatApi] Stream event error:", errorResult);
            onError(new Error(errorResult));
            controller.abort();
          }
        },
        onclose() {
          streamLog("sse", "connection-closed", { conversationId });
          // Only call onClose if [DONE] didn't already trigger it.
          // Connection drops without [DONE] (e.g. network failure) still need cleanup.
          if (!doneReceived) {
            onClose();
          }
        },
        onerror: (err) => {
          streamLogError("sse", "connection-error", {
            conversationId,
            detail: { message: err.message },
          });
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

  /** Stream id of the conversation's in-flight turn, or null when idle —
   *  the re-attach discovery for reloads (event log replays what was missed). */
  getActiveStream: async (conversationId: string): Promise<string | null> => {
    const response = await apiService.get<{ stream_id: string | null }>(
      `/conversations/${conversationId}/active-stream`,
      { silent: true },
    );
    return response.stream_id;
  },

  subscribeToExecutorStream: async (
    streamId: string,
    onMessage: (event: EventSourceMessage) => void,
    onClose: () => void,
    onError: (err: Error) => void,
    signal: AbortSignal,
    lastEventId?: string,
  ): Promise<void> => {
    let doneReceived = false;

    await fetchEventSource(
      `${process.env.NEXT_PUBLIC_API_BASE_URL}stream/${streamId}`,
      {
        method: "GET",
        openWhenHidden: true,
        headers: {
          Accept: "text/event-stream",
          ...desktopClientHeaders(),
          // Resume cursor — the backend replays everything after this entry.
          ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
        },
        credentials: "include",
        signal,
        onmessage(event) {
          if (event.data === "[DONE]") {
            doneReceived = true;
            onClose();
            return;
          }
          onMessage(event);
        },
        onclose() {
          streamLog("sse", "connection-closed");
          if (!doneReceived) {
            onClose();
          }
        },
        onerror(err) {
          streamLogError("sse", "connection-error", {
            detail: { message: err.message },
          });
          onError(err);
          throw err; // stops retry attempts
        },
      },
    );
  },

  /**
   * Deliver the result of a desktop-executed tool action back to the
   * backend, where the awaiting agent tool picks it up via Redis.
   */
  postDesktopToolResult: async (result: DesktopToolResult): Promise<void> => {
    await apiService.post("/desktop/tool-result", result, {
      silent: true,
    });
  },
};
