import { getAuthToken } from "@/features/auth/utils/auth-storage";
import { apiService } from "@/lib/api";
import { API_BASE_URL } from "@/lib/constants";

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

export interface ApiToolData {
  tool_name: string;
  data: Record<string, unknown>;
  timestamp?: string | null;
}

export interface ApiMessage {
  type: "user" | "bot";
  response: string;
  date: string;
  message_id: string;
  fileIds: string[];
  fileData: ApiFileData[];
  tool_data?: ApiToolData[];
  metadata?: Record<string, unknown>;
  replyToMessage?: ReplyToMessageData | null;
  reply_to_message?: ReplyToMessageData | null;
}

export interface ApiConversationDetail {
  _id: string;
  user_id: string;
  conversation_id: string;
  description: string;
  is_system_generated: boolean;
  system_purpose: string | null;
  is_unread: boolean;
  messages: ApiMessage[];
  createdAt: string;
  updatedAt?: string;
}

export interface ImageData {
  url: string;
  prompt: string;
  improvedPrompt?: string;
}

export interface MemoryData {
  [key: string]: unknown;
}

export interface ReplyToMessageData {
  id: string;
  content: string;
  role: "user" | "assistant";
}

export interface Message {
  id: string;
  text: string;
  isUser: boolean;
  timestamp: Date;
  fileIds?: string[];
  fileData?: ApiFileData[];
  toolData?: ApiToolData[];
  followUpActions?: string[];
  imageData?: ImageData | null;
  memoryData?: MemoryData | null;
  metadata?: Record<string, unknown>;
  replyToMessage?: ReplyToMessageData | null;
}

export interface ConversationDetail {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
  isUnread: boolean;
}

function normalizeMessage(apiMsg: ApiMessage): Message {
  const imageData = apiMsg.metadata?.image_data as ImageData | undefined;
  const memoryData = apiMsg.metadata?.memory_data as MemoryData | undefined;
  const replyToMessage =
    apiMsg.replyToMessage ?? apiMsg.reply_to_message ?? null;

  return {
    id: apiMsg.message_id,
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

export async function fetchMessages(
  conversationId: string,
): Promise<Message[]> {
  try {
    const conversation = await fetchConversation(conversationId);
    return conversation?.messages || [];
  } catch (error) {
    console.error("Error fetching messages:", error);
    return [];
  }
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

export async function cancelStream(streamId: string): Promise<boolean> {
  try {
    await apiService.post(`/cancel-stream/${streamId}`, {});
    return true;
  } catch (error) {
    console.warn("Error cancelling stream:", error);
    return false;
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
  fetchMessages,
  markConversationAsRead,
  markConversationAsUnread,
  deleteConversation,
  renameConversation,
  toggleStarConversation,
  deleteMessage,
  pinMessage,
  cancelStream,
  uploadFile,
  branchConversation,
  submitMessageFeedback,
};

export * from "./chat-stream";
