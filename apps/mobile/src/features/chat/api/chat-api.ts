import type {
  ApprovalDecisionResponse,
  ConversationEntriesPage,
  ImageData,
  LoadedConversation,
  MessageAccepted,
  Reaction,
  ReplyToMessageData,
  SelectedWorkflowDataOutput,
  SendMessageRequest,
  TodoRunWake,
} from "@gaia/shared/api/generated";

export type { ImageData, ReplyToMessageData } from "@gaia/shared/api/generated";

import type { ApprovalDecisionPayload, ToolDataEntry } from "@gaia/shared/chat";
import {
  type ConversationPage,
  ConversationPageSchema,
} from "@gaia/shared/conversation";
import { getAuthToken } from "@/features/auth/utils/auth-storage";
import { ApiError, apiService } from "@/lib/api";
import { API_BASE_URL } from "@/lib/constants";
import { readEventStream } from "@/lib/sse-client";

// 410 Gone: the approval was already resolved elsewhere.
const HTTP_GONE = 410;

export interface FileUploadResponse {
  fileId: string;
  fileName: string;
  fileSize: number;
  contentType: string;
  url?: string;
  description?: string;
  message?: string;
}

export interface ApiFileData {
  fileId: string;
  fileName?: string;
  fileSize?: number;
  contentType?: string;
  url?: string;
}

/** @deprecated Use ToolDataEntry from @gaia/shared/chat instead. */
export type ApiToolData = ToolDataEntry;

export interface Message {
  id: string;
  /** The message's place in its conversation's order; absent while a live row has none yet. */
  seq?: number;
  text: string;
  isUser: boolean;
  timestamp: Date;
  fileIds?: string[];
  fileData?: ApiFileData[];
  toolData?: ToolDataEntry[];
  followUpActions?: string[];
  imageData?: ImageData | null;
  pinned?: boolean;
  replyToMessage?: ReplyToMessageData | null;
  /**
   * Set when the turn producing this message failed. The streamed text (if
   * any) is preserved alongside it — mirrors web's FailedResponse, which shows
   * the partial bubble plus a retry affordance instead of wiping the text.
   */
  error?: string;
  /** GAIA's one emoji reaction on a user message. */
  reaction?: Reaction | null;
  /** A reply or task still streaming, or a send the server has not accepted yet. */
  inProgress?: boolean;
  /** A reply or task the user stopped. */
  stopped?: boolean;
  /** A send that never reached the server; its retry resends the same message. */
  sendFailed?: boolean;
  /** What woke a tracked todo's run; set on that run's user message. */
  todoRunWake?: TodoRunWake | null;
  /** The workflow whose run this user-side row started. */
  firedWorkflow?: SelectedWorkflowDataOutput | null;
}

/** The conversation's newest page of its log, as a load returns it. */
export async function fetchConversationPage(
  conversationId: string,
): Promise<ConversationPage> {
  return ConversationPageSchema.parse(
    await apiService.get<LoadedConversation>(
      `/conversations/${encodeURIComponent(conversationId)}`,
    ),
  );
}

/** The page of the log before beforeSeq, oldest first. */
export async function fetchEntriesBefore(
  conversationId: string,
  beforeSeq: number,
  limit: number,
): Promise<ConversationPage> {
  return ConversationPageSchema.parse(
    await apiService.get<ConversationEntriesPage>(
      `/conversations/${encodeURIComponent(conversationId)}/entries?before_seq=${beforeSeq}&limit=${limit}`,
    ),
  );
}

export async function markConversationAsRead(
  conversationId: string,
): Promise<boolean> {
  try {
    await apiService.patch(`/conversations/${conversationId}/read`, {});
    return true;
  } catch (error) {
    console.error("Error marking conversation as read:", error);
    return false;
  }
}

export async function deleteConversation(
  conversationId: string,
): Promise<boolean> {
  try {
    await apiService.delete(`/conversations/${conversationId}`);
    return true;
  } catch (error) {
    console.error("Error deleting conversation:", error);
    return false;
  }
}

export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<boolean> {
  try {
    await apiService.put(`/conversations/${conversationId}/description`, {
      description: title,
    });
    return true;
  } catch (error) {
    console.error("Error renaming conversation:", error);
    return false;
  }
}

export async function markConversationAsUnread(
  conversationId: string,
): Promise<boolean> {
  try {
    await apiService.patch(`/conversations/${conversationId}/unread`, {});
    return true;
  } catch (error) {
    console.error("Error marking conversation as unread:", error);
    return false;
  }
}

export async function toggleStarConversation(
  conversationId: string,
  starred: boolean,
): Promise<boolean> {
  try {
    await apiService.put(`/conversations/${conversationId}/star`, { starred });
    return true;
  } catch (error) {
    console.error("Error starring conversation:", error);
    return false;
  }
}

export async function deleteMessage(
  conversationId: string,
  messageId: string,
): Promise<boolean> {
  try {
    await apiService.delete(`/chat/${conversationId}/messages/${messageId}`);
    return true;
  } catch (error) {
    console.error("Error deleting message:", error);
    return false;
  }
}

/** Pin or unpin a message; false when the server refused. */
export async function pinMessage(
  conversationId: string,
  messageId: string,
  pinned: boolean,
): Promise<boolean> {
  try {
    await apiService.put(
      `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/pin`,
      { pinned },
    );
    return true;
  } catch (error) {
    console.error("Error pinning message:", error);
    return false;
  }
}

/** Accept a message into a conversation (a new one when the id is fresh); the reply arrives on its events. */
export function sendConversationMessage(
  conversationId: string,
  body: SendMessageRequest,
): Promise<MessageAccepted> {
  return apiService.post<MessageAccepted>(
    `/conversations/${encodeURIComponent(conversationId)}/messages`,
    body,
  );
}

/** Stop everything running in a conversation. */
export async function stopConversation(conversationId: string): Promise<void> {
  await apiService.post(
    `/conversations/${encodeURIComponent(conversationId)}/stop`,
  );
}

/** Follow a conversation's events after seq `after`, handing each data line over raw; resolves when the stream ends. */
export function subscribeToConversationEvents(
  conversationId: string,
  after: number,
  onData: (raw: string) => void,
  signal: AbortSignal,
): Promise<void> {
  return readEventStream(
    `/conversations/${encodeURIComponent(conversationId)}/events?after=${after}`,
    onData,
    signal,
  );
}

export async function postApprovalDecision(
  approvalId: string,
  decision: ApprovalDecisionPayload,
): Promise<ApprovalDecisionResponse> {
  try {
    return await apiService.post<ApprovalDecisionResponse>(
      `/approvals/${approvalId}/decision`,
      decision,
    );
  } catch (error) {
    // A 410 means the row already moved elsewhere — report it as not_found so
    // the card refreshes rather than painting over the real verdict. Any other
    // failure propagates to the card, which re-enables the buttons.
    if (error instanceof ApiError && error.status === HTTP_GONE)
      return { success: false, reason: "not_found" };
    throw error;
  }
}

export interface UploadFileInput {
  uri: string;
  name: string;
  mimeType: string;
}

export async function uploadFile(
  file: UploadFileInput,
): Promise<FileUploadResponse> {
  const token = await getAuthToken();
  if (!token) {
    throw new Error("Not authenticated");
  }

  const formData = new FormData();
  formData.append("file", {
    uri: file.uri,
    name: file.name,
    type: file.mimeType,
  } as unknown as Blob);

  const response = await fetch(`${API_BASE_URL}/upload`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
    },
    body: formData,
  });

  if (!response.ok) {
    const errorText = await response.text();
    console.error(`[API] Upload error ${response.status}: ${errorText}`);
    throw new Error(`Upload failed: ${response.status}`);
  }

  return response.json() as Promise<FileUploadResponse>;
}

export async function branchConversation(
  conversationId: string,
  messageId: string,
): Promise<string | null> {
  try {
    const response = await apiService.post<{ conversation_id: string }>(
      `/conversations/${conversationId}/branch`,
      { message_id: messageId },
    );
    return response.conversation_id;
  } catch (error) {
    console.error("Error branching conversation:", error);
    return null;
  }
}

export async function submitMessageFeedback(
  conversationId: string,
  messageId: string,
  feedback: "thumbsUp" | "thumbsDown",
): Promise<boolean> {
  try {
    await apiService.post(
      `/chat/${conversationId}/messages/${messageId}/feedback`,
      { feedback },
    );
    return true;
  } catch (error) {
    console.error("Error submitting feedback:", error);
    return false;
  }
}

export const chatApi = {
  fetchConversationPage,
  fetchEntriesBefore,
  markConversationAsRead,
  markConversationAsUnread,
  deleteConversation,
  renameConversation,
  toggleStarConversation,
  deleteMessage,
  pinMessage,
  sendConversationMessage,
  stopConversation,
  subscribeToConversationEvents,
  uploadFile,
  branchConversation,
  submitMessageFeedback,
  postApprovalDecision,
};
