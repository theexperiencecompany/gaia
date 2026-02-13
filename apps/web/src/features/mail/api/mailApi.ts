import { getQueryForTab } from "@/features/mail/utils/mailUtils";
import { apiService } from "@/lib/api";
import type { EmailActionResponse } from "@/types/api/mailApiTypes";
import type {
  EmailData,
  EmailImportanceSummary,
  EmailSummariesResponse,
  EmailsResponse,
  EmailThreadResponse,
  MailTab,
  SmartRepliesResponse,
} from "@/types/features/mailTypes";

export const mailApi = {
  // Fetch email by ID
  fetchEmailById: async (messageId: string): Promise<EmailData> => {
    const response = await apiService.get<{
      message: EmailData;
      status: string;
    }>(`/gmail/message/${messageId}`, {
      errorMessage: "Failed to fetch email",
    });
    return response.message;
  },

  // Mark email as read/unread (uses backend bulk endpoint with single message)
  markEmailAsRead: async (
    messageId: string,
    isRead: boolean,
  ): Promise<EmailActionResponse> => {
    const action = isRead ? "read" : "unread";
    await apiService.post(
      `/gmail/mark-as-${action}`,
      { message_ids: [messageId] },
      {
        errorMessage: `Failed to mark email as ${action}`,
      },
    );
    return { success: true, message: `Email marked as ${action}` };
  },

  // Star/unstar email (uses backend bulk endpoint with single message)
  toggleStarEmail: async (
    messageId: string,
    isStarred: boolean,
  ): Promise<EmailActionResponse> => {
    const action = isStarred ? "star" : "unstar";
    await apiService.post(
      `/gmail/${action}`,
      { message_ids: [messageId] },
      {
        successMessage: `Email ${action}red`,
        errorMessage: `Failed to ${action} email`,
      },
    );
    return { success: true, message: `Email ${action}red` };
  },

  // Archive email (uses backend bulk endpoint with single message)
  archiveEmail: async (messageId: string): Promise<EmailActionResponse> => {
    await apiService.post(
      `/gmail/archive`,
      { message_ids: [messageId] },
      {
        successMessage: "Email archived",
        errorMessage: "Failed to archive email",
      },
    );
    return { success: true, message: "Email archived" };
  },

  // Move email to trash (uses backend bulk endpoint with single message)
  trashEmail: async (messageId: string): Promise<EmailActionResponse> => {
    await apiService.post(
      `/gmail/trash`,
      { message_ids: [messageId] },
      {
        successMessage: "Email moved to trash",
        errorMessage: "Failed to move email to trash",
      },
    );
    return { success: true, message: "Email moved to trash" };
  },

  // Restore email from trash (uses backend bulk endpoint with single message)
  untrashEmail: async (messageId: string): Promise<EmailActionResponse> => {
    await apiService.post(
      `/gmail/untrash`,
      { message_ids: [messageId] },
      {
        successMessage: "Email restored from trash",
        errorMessage: "Failed to restore email from trash",
      },
    );
    return { success: true, message: "Email restored from trash" };
  },

  // Bulk operations
  bulkMarkAsRead: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await apiService.post(
      "/gmail/mark-as-read",
      {
        message_ids: messageIds,
      },
      {
        successMessage: `${messageIds.length} emails marked as read`,
        errorMessage: "Failed to mark emails as read",
      },
    );
    return {
      success: true,
      message: `${messageIds.length} emails marked as read`,
    };
  },

  bulkMarkAsUnread: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await apiService.post(
      "/gmail/mark-as-unread",
      {
        message_ids: messageIds,
      },
      {
        successMessage: `${messageIds.length} emails marked as unread`,
        errorMessage: "Failed to mark emails as unread",
      },
    );
    return {
      success: true,
      message: `${messageIds.length} emails marked as unread`,
    };
  },

  bulkStarEmails: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await apiService.post(
      "/gmail/star",
      {
        message_ids: messageIds,
      },
      {
        successMessage: `${messageIds.length} emails starred`,
        errorMessage: "Failed to star emails",
      },
    );
    return { success: true, message: `${messageIds.length} emails starred` };
  },

  bulkUnstarEmails: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await apiService.post(
      "/gmail/unstar",
      {
        message_ids: messageIds,
      },
      {
        successMessage: `${messageIds.length} emails unstarred`,
        errorMessage: "Failed to unstar emails",
      },
    );
    return {
      success: true,
      message: `${messageIds.length} emails unstarred`,
    };
  },

  bulkArchiveEmails: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await apiService.post(
      "/gmail/archive",
      {
        message_ids: messageIds,
      },
      {
        successMessage: `${messageIds.length} emails archived`,
        errorMessage: "Failed to archive emails",
      },
    );
    return { success: true, message: `${messageIds.length} emails archived` };
  },

  bulkTrashEmails: async (
    messageIds: string[],
  ): Promise<EmailActionResponse> => {
    await apiService.post(
      "/gmail/trash",
      {
        message_ids: messageIds,
      },
      {
        successMessage: `${messageIds.length} emails moved to trash`,
        errorMessage: "Failed to move emails to trash",
      },
    );
    return {
      success: true,
      message: `${messageIds.length} emails moved to trash`,
    };
  },

  // Search emails
  searchEmails: async (
    query: string,
  ): Promise<{
    messages: Array<EmailData>;
    nextPageToken?: string;
  }> => {
    return apiService.get(
      `/gmail/search?query=${encodeURIComponent(query)}`,
      {
        errorMessage: "Failed to search emails",
      },
    );
  },

  // Fetch emails by tab with pagination
  fetchEmailsByTab: async (
    tab: MailTab,
    pageToken?: string,
  ): Promise<EmailsResponse> => {
    const { endpoint, params } = getQueryForTab(tab);
    const maxResults = 20;

    if (endpoint === "drafts") {
      const data = await apiService.get<{
        drafts: EmailData[];
        nextPageToken?: string;
      }>(
        `/gmail/drafts?max_results=${maxResults}${pageToken ? `&page_token=${pageToken}` : ""}`,
      );
      return {
        emails: data.drafts || [],
        nextPageToken: data.nextPageToken,
      };
    }

    const searchParams = new URLSearchParams({
      max_results: String(maxResults),
      ...params,
    });
    if (pageToken) searchParams.set("page_token", pageToken);

    const data = await apiService.get<{
      messages: EmailData[];
      nextPageToken?: string;
    }>(`/gmail/search?${searchParams.toString()}`);
    return {
      emails: data.messages || [],
      nextPageToken: data.nextPageToken,
    };
  },

  // Reply to email using existing send endpoint with thread_id
  replyToEmail: async (data: {
    to: string;
    subject: string;
    body: string;
    threadId: string;
  }): Promise<{ message_id: string; status: string }> => {
    const formData = new FormData();
    formData.append("to", data.to);
    formData.append("subject", data.subject);
    formData.append("body", data.body);
    formData.append("thread_id", data.threadId);
    formData.append("is_html", "true");

    return apiService.post("/gmail/send", formData, {
      successMessage: "Reply sent successfully",
      errorMessage: "Failed to send reply",
    });
  },

  // Generate smart replies for an email
  generateSmartReplies: async (
    messageId: string,
  ): Promise<SmartRepliesResponse> => {
    return apiService.post<SmartRepliesResponse>(
      `/gmail/smart-replies/${messageId}`,
      {},
      {
        errorMessage: "Failed to generate smart replies",
        silent: true,
      },
    );
  },

  // Analyze email on demand
  analyzeEmail: async (
    messageId: string,
  ): Promise<{
    message_id: string;
    analysis: EmailImportanceSummary;
  }> => {
    return apiService.post(
      `/gmail/analyze/${messageId}`,
      {},
      {
        errorMessage: "Failed to analyze email",
        silent: true,
      },
    );
  },

  // Summarize email
  summarizeEmail: async (summaryRequest: {
    messageId: string;
    include_action_items?: boolean;
    max_length?: number;
  }): Promise<{ summary: string }> => {
    const { messageId, ...rest } = summaryRequest;
    return apiService.post(
      "/gmail/summarize",
      { message_id: messageId, ...rest },
      {
        errorMessage: "Failed to summarize email",
      },
    );
  },

  // Send email
  sendEmail: async (
    formData: FormData,
  ): Promise<{
    message_id: string;
    status: string;
    attachments_count: number;
  }> => {
    return apiService.post("/gmail/send", formData, {
      successMessage: "Email sent successfully",
      errorMessage: "Failed to send email",
    });
  },

  // Send draft email
  sendDraft: async (
    draftId: string,
  ): Promise<{
    message_id: string;
    thread_id: string;
    status: string;
    successful: boolean;
  }> => {
    return apiService.post(
      `/gmail/drafts/${draftId}/send`,
      {},
      {
        successMessage: "Draft sent successfully",
        errorMessage: "Failed to send draft",
      },
    );
  },

  // AI compose email
  composeWithAI: async (params: {
    subject: string;
    body: string;
    prompt: string;
    writingStyle: string;
    contentLength: string;
    clarityOption: string;
  }): Promise<{ subject: string; body: string }> => {
    return apiService.post("/mail/ai/compose", params, {
      errorMessage: "Failed to compose email with AI",
    });
  },

  // AI Email Analysis endpoints
  fetchEmailSummaries: async (
    limit: number = 50,
    importantOnly: boolean = false,
  ): Promise<EmailSummariesResponse> => {
    return apiService.get<EmailSummariesResponse>(
      `/gmail/importance-summaries?limit=${limit}&important_only=${importantOnly}`,
      {
        errorMessage: "Failed to fetch email summaries",
        silent: true,
      },
    );
  },

  fetchEmailSummaryById: async (
    messageId: string,
  ): Promise<{
    status: string;
    email: EmailImportanceSummary;
  } | null> => {
    try {
      return await apiService.get<{
        status: string;
        email: EmailImportanceSummary;
      }>(`/gmail/importance-summary/${messageId}`, {
        errorMessage: "Failed to fetch email summary",
        silent: true,
      });
    } catch {
      return null;
    }
  },

  fetchEmailSummaryByIds: async (
    messageIds: string[],
  ): Promise<{
    status: string;
    emails: Record<string, EmailImportanceSummary>;
    found_count: number;
    missing_count: number;
    found_message_ids: string[];
    missing_message_ids: string[];
  }> => {
    return apiService.post<{
      status: string;
      emails: Record<string, EmailImportanceSummary>;
      found_count: number;
      missing_count: number;
      found_message_ids: string[];
      missing_message_ids: string[];
    }>(
      "/gmail/importance-summaries/bulk",
      { message_ids: messageIds },
      {
        errorMessage: "Failed to fetch email summaries by IDs",
        silent: true,
      },
    );
  },

  // Fetch email thread
  fetchEmailThread: async (
    threadId: string,
    options?: { signal?: AbortSignal },
  ): Promise<EmailThreadResponse> => {
    return apiService.get<EmailThreadResponse>(`/gmail/thread/${threadId}`, {
      errorMessage: "Failed to fetch email thread",
      signal: options?.signal,
    });
  },
};
