import type { Schema } from "@shared/api/generated";
import { api } from "@/lib/api/typed";
import type { EmailActionResponse } from "@/types/api/mailApiTypes";
import {
  asEmailData,
  type EmailImportanceSummary,
  type EmailsResponse,
  type EmailThreadResponse,
} from "@/types/features/mailTypes";

/**
 * The importance-summary endpoints return each stored analysis as a raw
 * document; `EmailImportanceSummary` is that document as the mail UI reads it.
 */
const asImportanceSummary = (
  email: Record<string, unknown>,
): EmailImportanceSummary => email as unknown as EmailImportanceSummary;

export const mailApi = {
  // Fetch emails with pagination
  fetchEmails: async (pageToken?: string): Promise<EmailsResponse> => {
    const data = await api.get("/api/v1/gmail/messages", {
      query: { max_results: 20, pageToken },
    });
    return {
      emails: asEmailData(data.messages),
      nextPageToken: data.nextPageToken ?? undefined,
    };
  },

  // Fetch email by ID
  fetchEmailById: async (messageId: string) => {
    const data = await api.get("/api/v1/gmail/message/{message_id}", {
      path: { message_id: messageId },
      errorMessage: "Failed to fetch email",
    });
    if (!data.message) {
      throw new Error(`Email ${messageId} was not found`);
    }
    return asEmailData([data.message])[0];
  },

  // Mark email as read/unread (uses backend bulk endpoint with single message)
  markEmailAsRead: async (
    messageId: string,
    isRead: boolean,
  ): Promise<EmailActionResponse> => {
    const action = isRead ? "read" : "unread";
    const init = {
      body: { message_ids: [messageId] },
      errorMessage: `Failed to mark email as ${action}`,
    };
    await (isRead
      ? api.post("/api/v1/gmail/mark-as-read", init)
      : api.post("/api/v1/gmail/mark-as-unread", init));
    return { success: true, message: `Email marked as ${action}` };
  },

  // Star/unstar email (uses backend bulk endpoint with single message)
  toggleStarEmail: async (
    messageId: string,
    isStarred: boolean,
  ): Promise<EmailActionResponse> => {
    const action = isStarred ? "star" : "unstar";
    const init = {
      body: { message_ids: [messageId] },
      successMessage: `Email ${action}red`,
      errorMessage: `Failed to ${action} email`,
    };
    await (isStarred
      ? api.post("/api/v1/gmail/star", init)
      : api.post("/api/v1/gmail/unstar", init));
    return { success: true, message: `Email ${action}red` };
  },

  // Archive email (uses backend bulk endpoint with single message)
  archiveEmail: async (messageId: string): Promise<EmailActionResponse> => {
    await api.post("/api/v1/gmail/archive", {
      body: { message_ids: [messageId] },
      successMessage: "Email archived",
      errorMessage: "Failed to archive email",
    });
    return { success: true, message: "Email archived" };
  },

  // Move email to trash (uses backend bulk endpoint with single message)
  trashEmail: async (messageId: string): Promise<EmailActionResponse> => {
    await api.post("/api/v1/gmail/trash", {
      body: { message_ids: [messageId] },
      successMessage: "Email moved to trash",
      errorMessage: "Failed to move email to trash",
    });
    return { success: true, message: "Email moved to trash" };
  },

  // Restore email from trash (uses backend bulk endpoint with single message)
  untrashEmail: async (messageId: string): Promise<EmailActionResponse> => {
    await api.post("/api/v1/gmail/untrash", {
      body: { message_ids: [messageId] },
      successMessage: "Email restored from trash",
      errorMessage: "Failed to restore email from trash",
    });
    return { success: true, message: "Email restored from trash" };
  },

  // Bulk operations
  bulkMarkAsRead: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await api.post("/api/v1/gmail/mark-as-read", {
      body: { message_ids: messageIds },
      successMessage: `${messageIds.length} emails marked as read`,
      errorMessage: "Failed to mark emails as read",
    });
    return {
      success: true,
      message: `${messageIds.length} emails marked as read`,
    };
  },

  bulkMarkAsUnread: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await api.post("/api/v1/gmail/mark-as-unread", {
      body: { message_ids: messageIds },
      successMessage: `${messageIds.length} emails marked as unread`,
      errorMessage: "Failed to mark emails as unread",
    });
    return {
      success: true,
      message: `${messageIds.length} emails marked as unread`,
    };
  },

  bulkStarEmails: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await api.post("/api/v1/gmail/star", {
      body: { message_ids: messageIds },
      successMessage: `${messageIds.length} emails starred`,
      errorMessage: "Failed to star emails",
    });
    return { success: true, message: `${messageIds.length} emails starred` };
  },

  bulkUnstarEmails: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await api.post("/api/v1/gmail/unstar", {
      body: { message_ids: messageIds },
      successMessage: `${messageIds.length} emails unstarred`,
      errorMessage: "Failed to unstar emails",
    });
    return {
      success: true,
      message: `${messageIds.length} emails unstarred`,
    };
  },

  bulkArchiveEmails: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await api.post("/api/v1/gmail/archive", {
      body: { message_ids: messageIds },
      successMessage: `${messageIds.length} emails archived`,
      errorMessage: "Failed to archive emails",
    });
    return { success: true, message: `${messageIds.length} emails archived` };
  },

  bulkTrashEmails: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await api.post("/api/v1/gmail/trash", {
      body: { message_ids: messageIds },
      successMessage: `${messageIds.length} emails moved to trash`,
      errorMessage: "Failed to move emails to trash",
    });
    return {
      success: true,
      message: `${messageIds.length} emails moved to trash`,
    };
  },

  // Send email
  sendEmail: (formData: FormData) =>
    api.post("/api/v1/gmail/send", {
      body: formData,
      successMessage: "Email sent successfully",
      errorMessage: "Failed to send email",
    }),

  // Send draft email
  sendDraft: (draftId: string) =>
    api.post("/api/v1/gmail/drafts/{draft_id}/send", {
      path: { draft_id: draftId },
      successMessage: "Draft sent successfully",
      errorMessage: "Failed to send draft",
    }),

  // AI compose email
  composeWithAI: (params: Schema<"EmailRequest">) =>
    api.post("/api/v1/mail/ai/compose", {
      body: params,
      errorMessage: "Failed to compose email with AI",
    }),

  fetchEmailSummaryById: async (messageId: string) => {
    const data = await api.get(
      "/api/v1/gmail/importance-summary/{message_id}",
      {
        path: { message_id: messageId },
        errorMessage: "Failed to fetch email summary",
        silent: true,
      },
    );
    return { status: data.status, email: asImportanceSummary(data.email) };
  },

  fetchEmailSummaryByIds: async (
    messageIds: string[],
  ): Promise<
    Omit<Schema<"BulkEmailImportanceSummariesResponse">, "emails"> & {
      emails: Record<string, EmailImportanceSummary>;
    }
  > => {
    const data = await api.post("/api/v1/gmail/importance-summaries/bulk", {
      body: { message_ids: messageIds },
      errorMessage: "Failed to fetch email summaries by IDs",
      silent: true,
    });
    const emails: Record<string, EmailImportanceSummary> = {};
    for (const [id, email] of Object.entries(data.emails)) {
      emails[id] = asImportanceSummary(email);
    }
    return { ...data, emails };
  },

  // Fetch email thread
  fetchEmailThread: async (threadId: string): Promise<EmailThreadResponse> => {
    const data = await api.get("/api/v1/gmail/thread/{thread_id}", {
      path: { thread_id: threadId },
      errorMessage: "Failed to fetch email thread",
    });
    // Gmail's thread resource is forwarded verbatim; the web type is its shape.
    return {
      thread_id: data.thread_id,
      messages_count: data.messages_count,
      thread: data.thread as unknown as EmailThreadResponse["thread"],
    };
  },
};
