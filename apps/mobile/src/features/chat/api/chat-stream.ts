import type { StreamToolOutput, ToolDataEntry } from "@gaia/shared/chat";
import { parseChatStreamEvent } from "@gaia/shared/chat";
import { createSSEConnection, type SSEEvent } from "@/lib/sse-client";
import type {
  ApiFileData,
  ImageData,
  Message,
  ReplyToMessageData,
} from "./chat-api";

/** Kill the connection if no events (incl. keepalives) arrive for this long. */
const STREAM_STALL_TIMEOUT_MS = 45_000;

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
  /**
   * The SSE transport closed before the backend sent its done event — the
   * response is truncated. Consumers should keep the partial text but mark
   * the turn as failed (retryable), never as complete.
   */
  onTransportClosed?: () => void;
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

/** Emit a "generating image" progress signal from a raw payload object. */
function emitGeneratingImage(
  source: Record<string, unknown>,
  callbacks: StreamCallbacks,
): void {
  if (source.status !== "generating_image") return;
  callbacks.onProgress?.("Generating image...");
  callbacks.onImageGenerationStarted?.(
    typeof source.prompt === "string" ? source.prompt : "",
  );
}

/** Emit an image_data callback from a raw payload object, if well-formed. */
function emitImageData(
  source: Record<string, unknown>,
  callbacks: StreamCallbacks,
): void {
  if (typeof source.image_data !== "object" || source.image_data === null) {
    return;
  }
  const imageData = source.image_data as {
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

/** Extract progress/image signals from a `tool_calls_data` tool_data entry. */
function handleToolCallsData(
  entry: ToolDataEntry,
  callbacks: StreamCallbacks,
): void {
  if (
    entry.tool_name !== "tool_calls_data" ||
    typeof entry.data !== "object" ||
    entry.data === null
  ) {
    return;
  }
  const data = entry.data as Record<string, unknown>;

  if (typeof data.message === "string") {
    callbacks.onProgress?.(
      data.message,
      typeof data.tool_name === "string" ? data.tool_name : undefined,
    );
  }

  emitGeneratingImage(data, callbacks);
  emitImageData(data, callbacks);
}

/**
 * Handle a single parsed stream event.
 * Returns `true` when the stream is finished (done/error) and processing of
 * further events in the batch should stop.
 */
function handleParsedStreamEvent(
  parsed: ReturnType<typeof parseChatStreamEvent>[number],
  callbacks: StreamCallbacks,
): boolean {
  switch (parsed.type) {
    case "done":
      callbacks.onDone();
      return true;
    case "error":
      callbacks.onError?.(new Error(parsed.error));
      return true;
    case "conversation_initialized":
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
      return false;
    case "progress":
      callbacks.onProgress?.(parsed.message, parsed.tool_name);
      return false;
    case "tool_data":
      // Always fire onToolData so callers can persist it.
      callbacks.onToolData?.(parsed.entry);
      handleToolCallsData(parsed.entry, callbacks);
      return false;
    case "tool_output":
      // Web parity — the backend emits tool execution results on a
      // separate event keyed by tool_call_id. Hand it to the caller so
      // it can merge `output` into the matching tool_data entry
      // (mergeToolOutputIntoToolData from @gaia/shared/chat).
      callbacks.onToolOutput?.(parsed.output);
      return false;
    case "follow_up_actions":
      if (parsed.actions.length > 0) {
        callbacks.onFollowUpActions?.(parsed.actions);
      }
      return false;
    case "response":
      callbacks.onChunk(parsed.chunk);
      return false;
    case "unknown":
      // Legacy image_data/status shape in the raw payload.
      emitGeneratingImage(parsed.payload, callbacks);
      emitImageData(parsed.payload, callbacks);
      return false;
    default:
      // keepalive, token_usage, main_response_complete,
      // conversation_description, todo_progress — intentionally ignored.
      return false;
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

  // Set once the backend's own done event has been handled. A transport close
  // after that is normal; one BEFORE it means a truncated response.
  let sawBackendDone = false;

  const wrappedCallbacks: StreamCallbacks = {
    ...callbacks,
    onDone: () => {
      sawBackendDone = true;
      callbacks.onDone();
    },
  };

  return createSSEConnection(
    "/chat-stream",
    {
      onMessage: (event: SSEEvent) => {
        // Use the shared parser — identical event handling to the web app.
        const parsedEvents = parseChatStreamEvent(event.data);

        for (const parsed of parsedEvents) {
          const finished = handleParsedStreamEvent(parsed, wrappedCallbacks);
          if (finished) {
            return;
          }
        }
      },
      onError: (error) => {
        callbacks.onError?.(error);
      },
      onClose: () => {
        if (sawBackendDone) return; // already settled via onDone
        callbacks.onTransportClosed?.();
      },
    },
    {
      body,
      // The backend emits keepalives during long tool runs; complete silence
      // for this long means the stream is dead. use-chat settles the turn as
      // an error and keeps the partial text.
      stallTimeoutMs: STREAM_STALL_TIMEOUT_MS,
    },
  );
}
