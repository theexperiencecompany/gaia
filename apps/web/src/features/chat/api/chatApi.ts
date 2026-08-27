import {
  type EventSourceMessage,
  fetchEventSource,
} from "@microsoft/fetch-event-source";
import type {
  ApprovalDecisionPayload,
  BatchApprovalDecisionPayload,
  BatchApprovalDecisionResponse,
} from "@shared/chat";

import type { DesktopToolResult } from "@shared/desktop-tools";
import { apiService } from "@/lib/api/service";
import { desktopClientHeaders } from "@/lib/electron/api";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import { getBrowserTimezone } from "@/lib/timezone";
import { toast } from "@/lib/toast";
import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import { useComposerStore } from "@/stores/composerStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { ArtifactData } from "@/types/features/toolDataTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";
import {
  getErrorMessage,
  handleRateLimitError,
} from "@/utils/interceptorUtils";

/** Thrown when the backend rejects a send whose turn_id was already claimed —
 *  the original request is (or was) processing; the retry must not re-run. */
export class DuplicateTurnError extends Error {
  constructor() {
    super("This send was already accepted by the server");
    this.name = "DuplicateTurnError";
  }
}

/** Thrown when a send is rejected by a usage wall (429). The rate-limit
 *  upsell toast is shown at throw time, so downstream failure handling must
 *  not add a generic error toast on top. */
export class RateLimitError extends Error {
  constructor(message?: string) {
    super(message || "Usage limit reached");
    this.name = "RateLimitError";
  }
}

const HTTP_CONFLICT = 409;
const HTTP_GONE = 410;
const HTTP_TOO_MANY_REQUESTS = 429;

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
  /** `sawDone` is false when the connection ended without `[DONE]` — a
   *  truncated turn, not a finished one. */
  onClose: (sawDone: boolean) => void;
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

export interface SyncedConversation {
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
  artifacts?: ArtifactData[];
  /** Stream id of the conversation's in-flight turn, null when idle — the
   *  re-attach discovery for reloads, carried on the sync response so opening
   *  a conversation costs a single request. */
  active_stream_id: string | null;
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
  ): Promise<{ conversations: SyncedConversation[] }> => {
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
  uploadFile: async (
    file: File,
    conversationId?: string,
  ): Promise<FileUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    if (conversationId) {
      formData.append("conversation_id", conversationId);
    }

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
          // Usage wall (message count or cost budget exhausted): render the
          // rate-limit upsell UI here — the axios interceptor never sees this
          // request — and throw typed so failure handling skips its generic toast.
          if (response.status === HTTP_TOO_MANY_REQUESTS) {
            const data: unknown = await response.json().catch(() => undefined);
            if (!handleRateLimitError(data)) {
              toast.error("Too many requests. Please try again later.");
            }
            throw new RateLimitError(getErrorMessage(data));
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
          // Transport-level record of the raw frame, before any parsing or
          // dispatch can drop it. This and the executor subscription below are
          // the app's only two SSE readers, so nothing bypasses the recording.
          streamLog("sse", "frame", {
            conversationId,
            detail: { raw: event.data },
          });
          const errorResult = onMessage(event);

          if (event.data === "[DONE]") {
            doneReceived = true;
            onClose(true);
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
            onClose(false);
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

  subscribeToExecutorStream: async (
    streamId: string,
    onMessage: (event: EventSourceMessage) => void,
    onClose: (sawDone: boolean) => void,
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
          streamLog("sse", "frame", {
            detail: { raw: event.data, streamId },
          });
          if (event.data === "[DONE]") {
            doneReceived = true;
            onClose(true);
            return;
          }
          onMessage(event);
        },
        onclose() {
          streamLog("sse", "connection-closed");
          if (!doneReceived) {
            onClose(false);
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

  /**
   * Relay a HIL approval decision to the awaiting agent gate. Silent — the
   * caller surfaces real failures; a 410 (already resolved elsewhere) resolves
   * over the stream regardless, so it's swallowed here rather than surfaced.
   */
  postApprovalDecision: async (
    approvalId: string,
    decision: ApprovalDecisionPayload,
  ): Promise<void> => {
    try {
      await apiService.post(`/approvals/${approvalId}/decision`, decision, {
        silent: true,
      });
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response
        ?.status;
      if (status === HTTP_GONE) return;
      throw error;
    }
  },

  /**
   * Decide several pending approvals in one submission (the batch review's
   * "Approve all"/"Decline all"). Per-approval outcomes come back in the
   * response — an already-resolved item never fails the rest.
   */
  postApprovalBatchDecision: async (
    payload: BatchApprovalDecisionPayload,
  ): Promise<BatchApprovalDecisionResponse> => {
    return apiService.post<BatchApprovalDecisionResponse>(
      "/approvals/batch-decision",
      payload,
      { silent: true },
    );
  },
};
