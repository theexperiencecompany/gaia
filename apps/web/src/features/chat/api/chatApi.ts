import {
  type EventSourceMessage,
  fetchEventSource,
} from "@microsoft/fetch-event-source";
import type { Schema } from "@shared/api/generated";
import type {
  ApprovalDecisionPayload,
  BatchApprovalDecisionPayload,
} from "@shared/chat";

import type { DesktopToolResult } from "@shared/desktop-tools";
import { getSubscriptionRequiredDetail } from "@shared/types/subscription";
import { getErrorMessage } from "@/lib/api/errors";
import { api } from "@/lib/api/typed";
import { desktopClientHeaders } from "@/lib/electron/api";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import { getBrowserTimezone } from "@/lib/timezone";
import { toast } from "@/lib/toast";
import { useComposerStore } from "@/stores/composerStore";
import type { SelectedCalendarEventData } from "@/stores/composerStore.types";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { AttachedFileData } from "@/types/shared/fileTypes";
import {
  handleRateLimitError,
  subscriptionRequiredOfferFromDetail,
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

/** Thrown when chat-stream rejects a send with 402 (the user isn't on Pro).
 *  The paywall is opened at throw time, so downstream failure handling must
 *  not add a generic error toast on top. */
export class SubscriptionRequiredError extends Error {
  constructor(message?: string) {
    super(message || "Subscription required");
    this.name = "SubscriptionRequiredError";
  }
}

const HTTP_CONFLICT = 409;
const HTTP_PAYMENT_REQUIRED = 402;
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
  fileData: AttachedFileData[];
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

/** The API's enum; the members are the ones the web reads by name. */
export type SystemPurpose = Schema<"SystemPurpose">;

export const SystemPurpose = {
  EMAIL_PROCESSING: "email_processing",
  WORKFLOW_EXECUTION: "workflow_execution",
  /** The seeded Getting-started thread: the user's first screen after onboarding. */
  GETTING_STARTED: "getting_started",
  OTHER: "other",
} as const satisfies Record<string, SystemPurpose>;

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

export type Conversation = Schema<"ConversationSummary">;

/**
 * The stored message as the chat UI holds it. The client message adds its
 * own transient flags (loading/queued/failed) and reads the API's nullable
 * fields as optional; this is the one place that conversion is stated.
 */
export const toClientMessages = (
  messages: Schema<"MessageModel-Output">[],
): MessageType[] => messages as unknown as MessageType[];

export type FetchConversationsResponse = Schema<"ConversationListResponse">;

export type ConversationSyncItem = Schema<"ConversationSyncItem">;

export type SyncedConversation = Schema<"ConversationSyncRow">;

export const chatApi = {
  // Fetch conversations with pagination
  fetchConversations: (page = 1, limit = 20) =>
    api.get("/api/v1/conversations", {
      query: { page, limit },
      errorMessage: "Failed to fetch conversations",
    }),

  // Batch sync conversations - only fetch stale conversations
  batchSyncConversations: (conversations: ConversationSyncItem[]) =>
    api.post("/api/v1/conversations/batch-sync", {
      body: { conversations },
      errorMessage: "Failed to sync conversations",
      silent: true,
    }),

  // File upload
  uploadFile: (file: File, conversationId?: string) => {
    const formData = new FormData();
    formData.append("file", file);
    if (conversationId) {
      formData.append("conversation_id", conversationId);
    }

    // No errorMessage override: let the backend detail surface (e.g. the 413
    // "File size exceeds the N MB limit." or 415 unsupported-type message)
    // instead of masking it with a generic "Failed to upload file".
    return api.post("/api/v1/upload", { body: formData });
  },

  // Generate image
  generateImage: (prompt: string) =>
    api.post("/api/v1/image/generate", {
      body: { message: prompt },
      successMessage: "Image generated successfully",
      errorMessage: "Failed to generate image",
    }),

  // Pin/unpin message
  togglePinMessage: async (
    conversationId: string,
    messageId: string,
    pinned: boolean,
  ): Promise<void> => {
    await api.put(
      "/api/v1/conversations/{conversation_id}/messages/{message_id}/pin",
      {
        path: { conversation_id: conversationId, message_id: messageId },
        body: { pinned },
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
    await api.post("/api/v1/messages/{message_id}/feedback", {
      path: { message_id: messageId },
      body: { is_positive: isPositive },
      silent: true,
      errorMessage: "Failed to record feedback",
    });
  },

  // Fetch messages for a conversation
  fetchMessages: async (conversationId: string): Promise<MessageType[]> => {
    const response = await api.get("/api/v1/conversations/{conversation_id}", {
      path: { conversation_id: conversationId },
      errorMessage: "Failed to fetch messages",
    });
    return toClientMessages(response.messages ?? []);
  },

  // Star/unstar conversation
  toggleStarConversation: async (
    conversationId: string,
    starred: boolean,
  ): Promise<void> => {
    await api.put("/api/v1/conversations/{conversation_id}/star", {
      path: { conversation_id: conversationId },
      body: { starred },
      successMessage: starred
        ? "Conversation starred"
        : "Conversation unstarred",
      errorMessage: `Failed to ${starred ? "star" : "unstar"} conversation`,
    });
  },

  // Delete conversation
  deleteConversation: async (conversationId: string): Promise<void> => {
    await api.delete("/api/v1/conversations/{conversation_id}", {
      path: { conversation_id: conversationId },
      successMessage: "Conversation deleted",
      errorMessage: "Failed to delete conversation",
    });
  },

  // Delete all conversations
  deleteAllConversations: async (): Promise<void> => {
    await api.delete("/api/v1/conversations", {
      successMessage: "All conversations deleted",
      errorMessage: "Failed to delete conversations",
    });
  },

  // Rename conversation
  renameConversation: async (
    conversationId: string,
    title: string,
  ): Promise<void> => {
    await api.put("/api/v1/conversations/{conversation_id}/description", {
      path: { conversation_id: conversationId },
      body: { description: title },
      successMessage: "Conversation renamed",
      errorMessage: "Failed to rename conversation",
    });
  },

  // Mark conversation as read
  markAsRead: async (conversationId: string): Promise<void> => {
    await api.patch("/api/v1/conversations/{conversation_id}/read", {
      path: { conversation_id: conversationId },
    });
  },

  // Mark conversation as unread
  markAsUnread: async (conversationId: string): Promise<void> => {
    await api.patch("/api/v1/conversations/{conversation_id}/unread", {
      path: { conversation_id: conversationId },
    });
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
          // Paid-only gate: the user isn't on Pro. This is the core gated
          // endpoint, so this is the request most likely to hit it — the
          // axios interceptor never sees this request (it isn't axios), so
          // the paywall has to be opened here directly. Throw typed so
          // failure handling (turnSession.ts) skips its generic error toast.
          if (response.status === HTTP_PAYMENT_REQUIRED) {
            const data: unknown = await response.json().catch(() => undefined);
            const detail = getSubscriptionRequiredDetail(data);
            if (detail) {
              useUpgradeModalStore
                .getState()
                .openModal(subscriptionRequiredOfferFromDetail(detail), {
                  source: "chat_stream_402",
                });
            }
            throw new SubscriptionRequiredError(detail?.message);
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
    await api.post("/api/v1/desktop/tool-result", {
      body: result,
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
      await api.post("/api/v1/approvals/{approval_id}/decision", {
        path: { approval_id: approvalId },
        body: decision,
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
  postApprovalBatchDecision: async (payload: BatchApprovalDecisionPayload) =>
    api.post("/api/v1/approvals/batch-decision", {
      body: payload,
      silent: true,
    }),
};
