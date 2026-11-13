import type {
  ApprovalDecisionResponse,
  ImageData,
  MessageAccepted,
  MessageReaction,
  ReplyToMessageData,
  SelectedWorkflowDataOutput,
  SendMessageRequest,
  TodoRunWake,
} from "@gaia/shared/api/generated";

export type { ImageData, ReplyToMessageData } from "@gaia/shared/api/generated";

import type { ApprovalDecisionPayload, ToolDataEntry } from "@gaia/shared/chat";
import type { HistoryPage } from "@gaia/shared/conversation";
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

export interface ApiMessage {
  type: "user" | "bot";
  response: string;
  date: string;
  message_id: string;
  /** The message's place in its conversation's order. */
  seq: number;
  fileIds: string[];
  fileData: ApiFileData[];
  tool_data?: ToolDataEntry[];
  metadata?: Record<string, unknown>;
  replyToMessage?: ReplyToMessageData | null;
  reply_to_message?: ReplyToMessageData | null;
  reaction?: MessageReaction | null;
  /** What woke a tracked todo's run; set on that run's user message. */
  todo_run_wake?: TodoRunWake | null;
}

export interface ApiConversationDetail {
  _id: string;
  user_id: string;
  conversation_id: string;
  description: string;
  is_system_generated: boolean;
  system_purpose: string | null;
  is_unread: boolean;
  /** Messages older than the ones returned remain on the server. */
  has_older: boolean;
  messages: ApiMessage[];
  createdAt: string;
  updatedAt?: string;
}

export interface MemoryData {
  [key: string]: unknown;
}

export interface Message {
  id: string;
  /** The saved message's place in its conversation's order; absent on live rows. */
  seq?: number;
  text: string;
  isUser: boolean;
  timestamp: Date;
  fileIds?: string[];
  fileData?: ApiFileData[];
  toolData?: ToolDataEntry[];
  followUpActions?: string[];
  imageData?: ImageData | null;
  memoryData?: MemoryData | null;
  pinned?: boolean;
  metadata?: Record<string, unknown>;
  replyToMessage?: ReplyToMessageData | null;
  /**
   * Set when the turn producing this message failed. The streamed text (if
   * any) is preserved alongside it — mirrors web's FailedResponse, which shows
   * the partial bubble plus a retry affordance instead of wiping the text.
   */
  error?: string;
  /** GAIA's one emoji reaction on a user message. */
  reaction?: MessageReaction | null;
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

export interface ConversationDetail {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
  isUnread: boolean;
  hasOlder: boolean;
}

function normalizeMessage(apiMsg: ApiMessage): Message {
  const imageData = apiMsg.metadata?.image_data as ImageData | undefined;
  const memoryData = apiMsg.metadata?.memory_data as MemoryData | undefined;
  const replyToMessage =
    apiMsg.replyToMessage ?? apiMsg.reply_to_message ?? null;

  return {
    id: apiMsg.message_id,
    seq: apiMsg.seq,
    text: apiMsg.response,
    isUser: apiMsg.type === "user",
    timestamp: new Date(apiMsg.date),
    fileIds: apiMsg.fileIds,
    fileData: apiMsg.fileData,
    toolData: apiMsg.tool_data,
    imageData: imageData ?? null,
    memoryData: memoryData ?? null,
    metadata: apiMsg.metadata,
    replyToMessage,
    reaction: apiMsg.reaction ?? null,
    todoRunWake: apiMsg.todo_run_wake ?? null,
  };
}

function normalizeConversationDetail(
  apiConv: ApiConversationDetail,
): ConversationDetail {
  return {
    id: apiConv.conversation_id,
    title: apiConv.description || "Untitled conversation",
    messages: apiConv.messages.map(normalizeMessage),
    createdAt: new Date(apiConv.createdAt),
    updatedAt: new Date(apiConv.updatedAt || apiConv.createdAt),
    isUnread: apiConv.is_unread,
    hasOlder: apiConv.has_older,
  };
}

export async function fetchConversation(
  conversationId: string,
): Promise<ConversationDetail | null> {
  try {
    const response = await apiService.get<ApiConversationDetail>(
      `/conversations/${conversationId}`,
    );
    return normalizeConversationDetail(response);
  } catch (error) {
    console.error("Error fetching conversation:", error);
    return null;
  }
}

/** The page of saved messages before beforeSeq, oldest first. */
export async function fetchMessagesBefore(
  conversationId: string,
  beforeSeq: number,
  limit: number,
): Promise<HistoryPage<Message>> {
  const page = await apiService.get<HistoryPage<ApiMessage>>(
    `/conversations/${encodeURIComponent(conversationId)}/messages?before_seq=${beforeSeq}&limit=${limit}`,
  );
  return {
    messages: page.messages.map(normalizeMessage),
    has_more: page.has_more,
  };
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

export async function pinMessage(
  conversationId: string,
  messageId: string,
): Promise<boolean> {
  try {
    await apiService.post(
      `/chat/${conversationId}/messages/${messageId}/pin`,
      {},
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
  fetchConversation,
  fetchMessagesBefore,
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
