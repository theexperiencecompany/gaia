import { fetchEventSource } from "@microsoft/fetch-event-source";
import type {
  ConversationEntry,
  ConversationSummary,
  ConversationSyncItem,
  ConversationSyncRow,
  MessageAccepted,
  SendMessageRequest,
  SystemPurpose as SystemPurposeLiteral,
} from "@shared/api/generated";

export type { ConversationSyncItem } from "@shared/api/generated";

import { ApiError } from "@shared/api";
import type {
  ApprovalDecisionPayload,
  BatchApprovalDecisionPayload,
  BatchApprovalDecisionResponse,
} from "@shared/chat";
import type { DesktopToolResult } from "@shared/desktop-tools";
import { BATCH_OUTCOME_REASON } from "@/features/chat/utils/batchOutcome";
import {
  apiBaseUrl,
  clientHeaders,
  requestOriginHeaders,
} from "@/lib/api/client";
import {
  api,
  binaryField,
  formDataSerializer,
  type RequestOrigin,
} from "@/lib/api/typed";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import type { MessageType } from "@/types/features/convoTypes";

/** The events stream refused a conversation the server does not hold yet: its first send has not landed. */
export class ConversationNotFoundError extends Error {
  constructor(conversationId: string) {
    super(`Conversation ${conversationId} does not exist yet`);
    this.name = "ConversationNotFoundError";
  }
}

const HTTP_NOT_FOUND = 404;
const HTTP_GONE = 410;

// The server rejects a batch-decision body larger than this, so a big review
// sheet is chunked into requests of this size instead of 422ing as one.
const APPROVAL_BATCH_CHUNK_SIZE = 25;

/** The API's enum; the members are the ones the web reads by name. */

export type SystemPurpose = SystemPurposeLiteral;

export const SystemPurpose = {
  EMAIL_PROCESSING: "email_processing",
  WORKFLOW_EXECUTION: "workflow_execution",
  /** The seeded Getting-started thread: the user's first screen after onboarding. */
  GETTING_STARTED: "getting_started",
  OTHER: "other",
} as const satisfies Record<string, SystemPurposeLiteral>;

export type Conversation = ConversationSummary;

/**
 * The stored message as the chat UI holds it. The client message adds its
 * own transient flags (loading/queued/failed) and reads the API's nullable
 * fields as optional; this is the one place that conversion is stated.
 */
export const toClientMessages = (
  messages: ConversationEntry[],
): MessageType[] => messages as unknown as MessageType[];

export type SyncedConversation = ConversationSyncRow;

export const chatApi = {
  // Fetch conversations with pagination
  fetchConversations: (
    page = 1,
    limit = 20,
    { background }: RequestOrigin = {},
  ) =>
    api.get("/api/v1/conversations", {
      query: { page, limit },
      errorMessage: "Failed to fetch conversations",
      background,
    }),

  // Batch sync conversations - only fetch stale conversations
  batchSyncConversations: (
    conversations: ConversationSyncItem[],
    { background }: RequestOrigin = {},
  ) =>
    api.post("/api/v1/conversations/batch-sync", {
      body: { conversations },
      errorMessage: "Failed to sync conversations",
      silent: true,
      background,
    }),

  // File upload
  uploadFile: (file: File, conversationId?: string) =>
    // No errorMessage override: let the backend detail surface (e.g. the 413
    // "File size exceeds the N MB limit." or 415 unsupported-type message)
    // instead of masking it with a generic "Failed to upload file".
    api.post("/api/v1/upload", {
      body: { file: binaryField(file), conversation_id: conversationId },
      bodySerializer: formDataSerializer,
    }),

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

  fetchMessagesBefore: (
    conversationId: string,
    beforeSeq: number,
    limit: number,
  ) =>
    api.get("/api/v1/conversations/{conversation_id}/messages", {
      path: { conversation_id: conversationId },
      query: { before_seq: beforeSeq, limit },
      errorMessage: "Failed to load older messages",
    }),

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

  // Stop everything the conversation runs: its live turn, executor, subagents, approvals, browser job
  stopConversation: async (conversationId: string): Promise<void> => {
    await api.post("/api/v1/conversations/{conversation_id}/stop", {
      path: { conversation_id: conversationId },
      silent: true,
      errorMessage: "Failed to stop the conversation",
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

  /** Accept a message into a conversation; the server creates the conversation on its first message. */
  sendConversationMessage: (
    conversationId: string,
    body: SendMessageRequest,
  ): Promise<MessageAccepted> =>
    api.post("/api/v1/conversations/{conversation_id}/messages", {
      path: { conversation_id: conversationId },
      body,
      silent: true,
    }),

  /**
   * Follow a conversation's event stream from the log after seq `after`; resolves when
   * the server closes it. Each `data:` line is handed over raw for the caller to parse.
   */
  subscribeToConversationEvents: async (
    conversationId: string,
    after: number,
    onData: (raw: string) => void,
    signal: AbortSignal,
  ): Promise<void> => {
    await fetchEventSource(
      `${apiBaseUrl}/conversations/${encodeURIComponent(conversationId)}/events?after=${after}`,
      {
        method: "GET",
        openWhenHidden: true,
        headers: {
          Accept: "text/event-stream",
          ...clientHeaders(),
          ...requestOriginHeaders(true),
        },
        credentials: "include",
        signal,
        async onopen(response) {
          if (response.status === HTTP_NOT_FOUND) {
            throw new ConversationNotFoundError(conversationId);
          }
          if (
            !response.ok ||
            !response.headers.get("content-type")?.includes("text/event-stream")
          ) {
            throw new Error(
              `Unexpected conversation events response (${response.status})`,
            );
          }
        },
        onmessage(event) {
          streamLog("sse", "frame", {
            conversationId,
            detail: { raw: event.data },
          });
          onData(event.data);
        },
        onclose() {
          streamLog("sse", "connection-closed", { conversationId });
        },
        onerror(err) {
          streamLogError("sse", "connection-error", {
            conversationId,
            detail: { message: err.message },
          });
          // The caller owns reconnecting, from the log, with its own backoff.
          throw err;
        },
      },
    );
  },

  /**
   * Deliver the result of a desktop-executed tool action back to the
   * backend, where the awaiting agent tool picks it up via Redis.
   */
  postDesktopToolResult: async (result: DesktopToolResult): Promise<void> => {
    // The agent asked for this tool run; the user did nothing.
    await api.post("/api/v1/desktop/tool-result", {
      body: result,
      silent: true,
      background: true,
    });
  },

  /**
   * Relay a HIL approval decision to the awaiting agent gate. Silent — the
   * caller surfaces real failures. A 410 (already resolved elsewhere) is
   * reported as not_found instead of success: settling the tapped verdict
   * would paint over the real one, so the caller refreshes instead.
   * Returns the relay outcome so callers can tell a commit from a stale tap:
   * `success:false` means the row moved under the client — refresh, don't retry.
   */
  postApprovalDecision: async (
    approvalId: string,
    decision: ApprovalDecisionPayload,
  ): Promise<{
    success: boolean;
    reason?: string | null;
    status?: string | null;
  }> => {
    try {
      return await api.post("/api/v1/approvals/{approval_id}/decision", {
        path: { approval_id: approvalId },
        body: decision,
        silent: true,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === HTTP_GONE)
        return { success: false, reason: "not_found" };
      throw error;
    }
  },

  /**
   * Decide several pending approvals in one submission (the batch review's
   * "Approve all"/"Decline all"), chunked to the server's 25-item cap. Chunks
   * commit independently, so a failed chunk comes back as per-item "error"
   * outcomes beside the committed ones; throws only when every chunk failed.
   */
  postApprovalBatchDecision: async (
    payload: BatchApprovalDecisionPayload,
  ): Promise<BatchApprovalDecisionResponse> => {
    const chunks: BatchApprovalDecisionPayload["decisions"][] = [];
    for (
      let i = 0;
      i < payload.decisions.length;
      i += APPROVAL_BATCH_CHUNK_SIZE
    ) {
      chunks.push(payload.decisions.slice(i, i + APPROVAL_BATCH_CHUNK_SIZE));
    }
    // Disjoint slices with no ordering dependency (chunked only for the 25-item
    // cap), so they fan out in parallel rather than serially.
    const results = await Promise.allSettled(
      chunks.map((decisions) =>
        api.post("/api/v1/approvals/batch-decision", {
          body: { decisions },
          silent: true,
        }),
      ),
    );
    const firstFailure = results.find((r) => r.status === "rejected");
    if (firstFailure && results.every((r) => r.status === "rejected")) {
      throw firstFailure.reason;
    }
    return {
      outcomes: results.flatMap((result, i) =>
        result.status === "fulfilled"
          ? result.value.outcomes
          : chunks[i].map(({ approval_id }) => ({
              approval_id,
              resolved: false,
              reason: BATCH_OUTCOME_REASON.ERROR,
            })),
      ),
    };
  },
};
