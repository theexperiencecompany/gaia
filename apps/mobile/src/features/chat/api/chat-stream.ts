import {
  parseChatStreamEvent,
  type StreamToolDataEntry,
  type StreamToolOutput,
  type TodoProgressSnapshot,
} from "@gaia/shared/chat";

import { createSSEConnection, type SSEEvent } from "@/lib/sse-client";
import type { ApiFileData, Message } from "./chat-api";

export interface StreamCallbacks {
  onChunk: (text: string) => void;
  onConversationCreated?: (
    conversationId: string,
    userMessageId: string,
    botMessageId: string,
    description?: string | null,
  ) => void;
  onProgress?: (message: string, toolName?: string) => void;
  onToolData?: (entry: StreamToolDataEntry) => void;
  onToolOutput?: (output: StreamToolOutput) => void;
  onTodoProgress?: (snapshot: TodoProgressSnapshot) => void;
  onStreamId?: (streamId: string) => void;
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

  let streamFinished = false;
  const finishOnce = () => {
    if (streamFinished) return;
    streamFinished = true;
    callbacks.onDone();
  };

  return createSSEConnection(
    "/chat-stream",
    {
      onMessage: (event: SSEEvent) => {
        const parsedEvents = parseChatStreamEvent(event.data);

        for (const parsed of parsedEvents) {
          if (parsed.type === "done") {
            finishOnce();
            return;
          }

          if (parsed.type === "error") {
            callbacks.onError?.(new Error(parsed.error));
            return;
          }

          if (parsed.type === "conversation_initialized") {
            if (parsed.stream_id) {
              callbacks.onStreamId?.(parsed.stream_id);
            }

            if (
              parsed.conversation_id &&
              parsed.bot_message_id &&
              parsed.user_message_id
            ) {
              callbacks.onConversationCreated?.(
                parsed.conversation_id,
                parsed.user_message_id,
                parsed.bot_message_id,
                parsed.conversation_description,
              );
            }
            continue;
          }

          if (parsed.type === "progress") {
            callbacks.onProgress?.(parsed.message, parsed.tool_name);
            continue;
          }

          if (parsed.type === "tool_data") {
            callbacks.onToolData?.(parsed.entry);
            continue;
          }

          if (parsed.type === "tool_output") {
            callbacks.onToolOutput?.(parsed.output);
            continue;
          }

          if (parsed.type === "todo_progress") {
            callbacks.onTodoProgress?.(parsed.snapshot);
            continue;
          }

          if (parsed.type === "response") {
            callbacks.onChunk(parsed.chunk);
            continue;
          }

          if (
            parsed.type === "follow_up_actions" &&
            parsed.actions.length > 0
          ) {
            callbacks.onFollowUpActions?.(parsed.actions);
          }
        }
      },
      onError: (error) => {
        callbacks.onError?.(error);
      },
      onClose: () => {
        finishOnce();
      },
    },
    { body },
  );
}
