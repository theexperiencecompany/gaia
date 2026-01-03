import { createSSEConnection, type SSEEvent } from "@/lib/sse-client";
import type { ApiFileData, Message } from "./chat-api";

export interface StreamCallbacks {
  onChunk: (text: string) => void;
  onConversationCreated?: (
    conversationId: string,
    userMessageId: string,
    botMessageId: string,
  ) => void;
  onProgress?: (message: string, toolName?: string) => void;
  onFollowUpActions?: (actions: string[]) => void;
  onDone: () => void;
  onError?: (error: Error) => void;
}

export interface ChatStreamRequest {
  message: string;
  conversationId?: string | null;
  messages?: Message[];
  fileIds?: string[];
  fileData?: ApiFileData[];
  selectedTool?: string | null;
  toolCategory?: string | null;
}

interface StreamEventData {
  type?: string;
  content?: string;
  conversation_id?: string;
  message_id?: string;
  response?: string;
  error?: string;
  bot_message_id?: string;
  user_message_id?: string;
  main_response_complete?: boolean;
  follow_up_actions?: string[];
  progress?: {
    message: string;
    tool_name?: string;
    tool_category?: string;
  };
}

function parseEventData(data: string): StreamEventData | null {
  if (data === "[DONE]") {
    return { type: "done" };
  }

  try {
    return JSON.parse(data);
  } catch {
    return { type: "content", content: data };
  }
}

export async function fetchChatStream(
  request: ChatStreamRequest,
  callbacks: StreamCallbacks,
): Promise<AbortController> {
  const {
    message,
    conversationId,
    messages = [],
    fileIds = [],
    fileData = [],
    selectedTool = null,
    toolCategory = null,
  } = request;

  const formattedMessages = messages
    .slice(-30)
    .filter((msg) => msg.text.trim().length > 0)
    .map((msg) => ({
      role: msg.isUser ? "user" : "assistant",
      content: msg.text,
    }));

  const body = {
    conversation_id: conversationId || null,
    message,
    fileIds,
    fileData,
    selectedTool,
    toolCategory,
    messages: formattedMessages,
  };

  return createSSEConnection(
    "/chat-stream",
    {
      onMessage: (event: SSEEvent) => {
        const parsed = parseEventData(event.data);

        if (!parsed) return;

        if (parsed.type === "done" || event.data === "[DONE]") {
          callbacks.onDone();
          return;
        }

        if (parsed.error) {
          callbacks.onError?.(new Error(parsed.error));
          return;
        }

        // Log all parsed events for debugging
        console.log(
          "[chat-stream] Parsed event:",
          JSON.stringify(parsed, null, 2),
        );

        // First event contains conversation_id and message IDs
        if (
          parsed.conversation_id &&
          parsed.bot_message_id &&
          parsed.user_message_id
        ) {
          console.log(
            "[chat-stream] Conversation created:",
            parsed.conversation_id,
          );
          callbacks.onConversationCreated?.(
            parsed.conversation_id,
            parsed.user_message_id,
            parsed.bot_message_id,
          );
        }

        // Progress updates (tool execution status)
        if (parsed.progress) {
          console.log("[chat-stream] Progress:", parsed.progress);
          callbacks.onProgress?.(
            parsed.progress.message,
            parsed.progress.tool_name,
          );
        }

        // Stream response chunks
        if (parsed.response) {
          callbacks.onChunk(parsed.response);
        }

        // Follow up actions
        if (parsed.follow_up_actions && parsed.follow_up_actions.length > 0) {
          callbacks.onFollowUpActions?.(parsed.follow_up_actions);
        }
      },
      onError: (error) => {
        console.log("[chat-stream] Error:", error);
        callbacks.onError?.(error);
      },
      onClose: () => {
        console.log("[chat-stream] Connection closed");
        callbacks.onDone();
      },
    },
    { body },
  );
}
