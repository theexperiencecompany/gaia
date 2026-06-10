import type { StreamToolOutput, ToolDataEntry } from "@gaia/shared/chat";
import { parseChatStreamEvent } from "@gaia/shared/chat";
import { createSSEConnection, type SSEEvent } from "@/lib/sse-client";
import type {
  ApiFileData,
  ImageData,
  Message,
  ReplyToMessageData,
} from "./chat-api";

export interface StreamCallbacks {
  onChunk: (text: string) => void;
  onConversationCreated?: (
    conversationId: string,
    userMessageId: string,
    botMessageId: string,
    description?: string | null,
  ) => void;
  /** Called once with the stream_id received from the backend, used for cancellation. */
  onStreamId?: (streamId: string) => void;
  onProgress?: (message: string, toolName?: string) => void;
  onFollowUpActions?: (actions: string[]) => void;
  /** Called for each tool_data entry received during streaming. */
  onToolData?: (entry: ToolDataEntry) => void;
  /**
   * Called when the backend emits a tool_output event — the actual result
   * string for a tool call, keyed by tool_call_id. Mirrors web's
   * handleToolOutput; the consumer is expected to merge `output` into the
   * matching tool_data entry (use mergeToolOutputIntoToolData from
   * @gaia/shared/chat).
   */
  onToolOutput?: (output: StreamToolOutput) => void;
  onImageGenerationStarted?: (prompt: string) => void;
  onImageData?: (data: ImageData) => void;
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
  workflowId?: string | null;
  replyToMessage?: ReplyToMessageData | null;
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
    workflowId = null,
    replyToMessage = null,
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
    workflow_id: workflowId || null,
    replyToMessage: replyToMessage || null,
    messages: formattedMessages,
  };

  return createSSEConnection(
    "/chat-stream",
    {
      onMessage: (event: SSEEvent) => {
        // Use the shared parser — identical event handling to the web app.
        const parsedEvents = parseChatStreamEvent(event.data);

        for (const parsed of parsedEvents) {
          if (parsed.type === "done") {
            callbacks.onDone();
            return;
          }

          if (parsed.type === "error") {
            callbacks.onError?.(new Error(parsed.error));
            return;
          }

          if (parsed.type === "keepalive" || parsed.type === "token_usage") {
            continue;
          }

          if (parsed.type === "main_response_complete") {
            continue;
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

          if (parsed.type === "conversation_description") {
            continue;
          }

          if (parsed.type === "progress") {
            callbacks.onProgress?.(parsed.message, parsed.tool_name);
            continue;
          }

          if (parsed.type === "tool_data") {
            // Always fire onToolData so callers can persist it.
            callbacks.onToolData?.(parsed.entry);

            // Extract loading text from tool_calls_data entries (same as web).
            if (
              parsed.entry.tool_name === "tool_calls_data" &&
              typeof parsed.entry.data === "object" &&
              parsed.entry.data !== null
            ) {
              const data = parsed.entry.data as Record<string, unknown>;

              if (typeof data.message === "string") {
                callbacks.onProgress?.(
                  data.message,
                  typeof data.tool_name === "string"
                    ? data.tool_name
                    : undefined,
                );
              }

              if (data.status === "generating_image") {
                callbacks.onProgress?.("Generating image...");
                callbacks.onImageGenerationStarted?.(
                  typeof data.prompt === "string" ? data.prompt : "",
                );
              }

              if (
                typeof data.image_data === "object" &&
                data.image_data !== null
              ) {
                const imageData = data.image_data as {
                  url?: string;
                  prompt?: string;
                  improvedPrompt?: string;
                };
                if (typeof imageData.url === "string" && imageData.url) {
                  callbacks.onImageData?.({
                    url: imageData.url,
                    prompt: imageData.prompt ?? "",
                    improvedPrompt: imageData.improvedPrompt,
                  });
                }
              }
            }
            continue;
          }

          if (parsed.type === "tool_output") {
            // Web parity — the backend emits tool execution results on a
            // separate event keyed by tool_call_id. Hand it to the caller so
            // it can merge `output` into the matching tool_data entry
            // (mergeToolOutputIntoToolData from @gaia/shared/chat).
            callbacks.onToolOutput?.(parsed.output);
            continue;
          }

          if (parsed.type === "todo_progress") {
            continue;
          }

          if (parsed.type === "follow_up_actions") {
            if (parsed.actions.length > 0) {
              callbacks.onFollowUpActions?.(parsed.actions);
            }
            continue;
          }

          if (parsed.type === "response") {
            callbacks.onChunk(parsed.chunk);
            continue;
          }

          // unknown — check for legacy image_data/status shape in the raw payload
          if (parsed.type === "unknown") {
            const payload = parsed.payload;

            if (
              typeof payload.status === "string" &&
              payload.status === "generating_image"
            ) {
              callbacks.onProgress?.("Generating image...");
              callbacks.onImageGenerationStarted?.(
                typeof payload.prompt === "string" ? payload.prompt : "",
              );
            }

            if (
              typeof payload.image_data === "object" &&
              payload.image_data !== null
            ) {
              const imageData = payload.image_data as {
                url?: string;
                prompt?: string;
                improvedPrompt?: string;
              };
              if (typeof imageData.url === "string" && imageData.url) {
                callbacks.onImageData?.({
                  url: imageData.url,
                  prompt: imageData.prompt ?? "",
                  improvedPrompt: imageData.improvedPrompt,
                });
              }
            }
          }
        }
      },
      onError: (error) => {
        callbacks.onError?.(error);
      },
      onClose: () => {
        callbacks.onDone();
      },
    },
    { body },
  );
}
