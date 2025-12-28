/**
 * Chat Streaming API
 * SSE-based streaming for real-time chat responses
 */

import { createSSEConnection, type SSEEvent } from "@/lib/sse-client";
import type { Message } from "./chat-api";

// =============================================================================
// Types
// =============================================================================

export interface StreamCallbacks {
  /** Called for each text chunk received */
  onChunk: (text: string) => void;
  /** Called when a complete message is received (with message_id) */
  onMessageComplete?: (data: StreamCompleteData) => void;
  /** Called when streaming is done */
  onDone: () => void;
  /** Called on error */
  onError?: (error: Error) => void;
}

export interface StreamCompleteData {
  messageId: string;
  conversationId: string;
  response?: string;
}

export interface ChatStreamRequest {
  message: string;
  conversationId?: string | null;
  messages?: Message[];
  fileIds?: string[];
  fileData?: Array<{
    fileId: string;
    fileName?: string;
    fileSize?: number;
    contentType?: string;
    url?: string;
  }>;
  selectedTool?: string | null;
  toolCategory?: string | null;
}

// =============================================================================
// Stream Data Parsing
// =============================================================================

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
}

function parseEventData(data: string): StreamEventData | null {
  if (data === "[DONE]") {
    return { type: "done" };
  }
  
  try {
    return JSON.parse(data);
  } catch {
    // If not JSON, treat as raw text content
    return { type: "content", content: data };
  }
}

// =============================================================================
// Chat Stream Function
// =============================================================================

/**
 * Start a streaming chat request
 * 
 * @example
 * ```ts
 * const abort = await fetchChatStream({
 *   message: "Hello!",
 *   conversationId: "abc-123",
 *   callbacks: {
 *     onChunk: (text) => setResponse(prev => prev + text),
 *     onDone: () => setIsStreaming(false),
 *     onError: (err) => console.error(err),
 *   }
 * });
 * 
 * // To cancel:
 * abort.abort();
 * ```
 */
export async function fetchChatStream(
  request: ChatStreamRequest,
  callbacks: StreamCallbacks
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

  // Format messages for the API (last 30, non-empty)
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

  console.log("[ChatStream] Request body:", JSON.stringify(body, null, 2));

  return createSSEConnection(
    "/chat-stream",
    {
      onMessage: (event: SSEEvent) => {
        console.log("[ChatStream] Raw SSE event:", event.data);
        
        const parsed = parseEventData(event.data);
        console.log("[ChatStream] Parsed event:", parsed);
        
        if (!parsed) return;

        // Handle [DONE] signal
        if (parsed.type === "done" || event.data === "[DONE]") {
          console.log("[ChatStream] Stream done");
          callbacks.onDone();
          return;
        }

        // Handle error
        if (parsed.error) {
          console.log("[ChatStream] Error:", parsed.error);
          callbacks.onError?.(new Error(parsed.error));
          return;
        }

        // Handle text content (backend sends 'response' field)
        if (parsed.response) {
          console.log("[ChatStream] Chunk:", parsed.response);
          callbacks.onChunk(parsed.response);
        }

        // Handle message IDs from initial event
        if (parsed.bot_message_id) {
          console.log("[ChatStream] Message IDs received:", parsed.bot_message_id);
          // We can use this to update the message ID later
        }

        // Handle message completion with metadata
        if (parsed.message_id && parsed.conversation_id) {
          console.log("[ChatStream] Message complete:", parsed.message_id);
          callbacks.onMessageComplete?.({
            messageId: parsed.message_id,
            conversationId: parsed.conversation_id,
            response: parsed.response,
          });
        }
      },
      onError: (error) => {
        console.log("[ChatStream] Connection error:", error);
        callbacks.onError?.(error);
      },
      onClose: () => {
        callbacks.onDone();
      },
    },
    { body }
  );
}
