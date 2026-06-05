import type { EventSourceMessage } from "@microsoft/fetch-event-source";
import {
  mergeToolOutputIntoToolData,
  parseChatStreamEvent,
  type SubagentEndPayload,
  type SubagentStartPayload,
  upsertTodoProgressToolData,
} from "@shared/chat";
import type {
  SubagentGroupData,
  ToolCallEntry,
  ToolDataEntry,
} from "@/config/registries/toolRegistry";
import { parseStreamData } from "@/features/chat/hooks/useStreamDataParser";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/stores/chatStore";
import { useLoadingStore } from "@/stores/loadingStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { TodoProgressSnapshot } from "@/types/features/todoProgressTypes";
import { updateSubagentInToolData } from "./subagentTree";
import type { StreamContext } from "./types";

export interface StreamHandlerDeps {
  ctx: StreamContext;
  updateBotMessage: (overrides: Partial<MessageType>) => void;
  updateBotMessageInStore: (conversationId: string) => void;
  schedulePersist: (conversationId: string) => void;
  resolveConversationId: () => string | null;
  handleNewConversation: (data: {
    conversation_id: string;
    conversation_description: string | null;
    bot_message_id?: string;
    user_message_id?: string;
    stream_id?: string;
  }) => Promise<void>;
  handleExistingConversationMessages: (data: {
    user_message_id: string;
    bot_message_id: string;
    stream_id?: string;
  }) => Promise<void>;
  handleConversationDescriptionUpdate: (
    conversationId: string,
    description: string,
  ) => Promise<void>;
}

// The discriminated-union element type that parseChatStreamEvent yields.
type ParsedStreamEvent = ReturnType<typeof parseChatStreamEvent>[number];

// Log and shape a catch-block error into the user-facing stream-error string.
// Lives at module scope so it doesn't inflate handleStreamEvent's cognitive
// complexity with the inline ternaries it used to carry.
function formatStreamError(error: unknown, eventData: string): string {
  console.error("[useChatStream] Error handling stream event:", {
    error,
    errorMessage: error instanceof Error ? error.message : "Unknown error",
    stack: error instanceof Error ? error.stack : undefined,
    eventData,
  });
  const errorMessage = error instanceof Error ? error.message : "Unknown error";
  return `Error processing stream data: ${errorMessage}`;
}

// Pull the loading-indicator hints out of a tool_data event's payload (returns null if none).
function readToolDataLoadingHints(data: unknown): {
  message: string;
  toolName?: string;
  toolCategory?: string;
  integrationName?: string;
  iconUrl?: string;
  showCategory: boolean;
} | null {
  if (typeof data !== "object" || data === null) return null;
  const d = data as Record<string, unknown>;
  if (typeof d.message !== "string" || d.message.length === 0) return null;
  return {
    message: d.message,
    toolName: typeof d.tool_name === "string" ? d.tool_name : undefined,
    toolCategory:
      typeof d.tool_category === "string" ? d.tool_category : undefined,
    integrationName:
      typeof d.integration_name === "string" ? d.integration_name : undefined,
    iconUrl: typeof d.icon_url === "string" ? d.icon_url : undefined,
    showCategory: (d.show_category as boolean) ?? true,
  };
}

export const createStreamHandlers = (deps: StreamHandlerDeps) => {
  const {
    ctx,
    updateBotMessage,
    updateBotMessageInStore,
    schedulePersist,
    handleNewConversation,
    handleExistingConversationMessages,
    handleConversationDescriptionUpdate,
  } = deps;

  const {
    refs,
    streamInProgressRef,
    setIsLoading,
    setLoadingText,
    resetLoadingText,
  } = ctx;

  // Trigger an IndexedDB persist for the current bot message if we have an
  // active conversation + message_id. Used as a tail step on every handler.
  const persistIfReady = (): void => {
    const conversationId =
      refs.current.newConversation.id ||
      useChatStore.getState().activeConversationId;
    if (refs.current.botMessage?.message_id && conversationId) {
      schedulePersist(conversationId);
    }
  };

  const applyToolDataLoadingHints = (data: unknown): void => {
    const hints = readToolDataLoadingHints(data);
    if (!hints) return;
    const { message, ...options } = hints;
    setLoadingText(message, options);
  };

  const handleToolData = (
    toolData: ToolDataEntry & { subagent_id?: string },
  ) => {
    const existingToolData = refs.current.botMessage?.tool_data ?? [];

    // Route tool_calls_data entries into the matching subagent group by event's own subagent_id.
    if (toolData.subagent_id && toolData.tool_name === "tool_calls_data") {
      const updatedToolData = updateSubagentInToolData(
        existingToolData,
        toolData.subagent_id,
        (g) => ({
          ...g,
          tool_calls: [...g.tool_calls, toolData.data as ToolCallEntry],
        }),
      );
      updateBotMessage({ tool_data: updatedToolData });
      applyToolDataLoadingHints(toolData.data);
      persistIfReady();
      return;
    }

    // Root-level tool_data entry — append and (only for tool_calls_data) surface
    // the loading indicator.
    updateBotMessage({ tool_data: [...existingToolData, toolData] });
    if (toolData.tool_name === "tool_calls_data") {
      applyToolDataLoadingHints(toolData.data);
    }
    persistIfReady();
  };

  const handleToolOutput = (toolOutput: {
    tool_call_id: string;
    output: string;
    subagent_id?: string;
  }) => {
    // Route tool outputs into the matching subagent group by event's own subagent_id.
    if (toolOutput.subagent_id) {
      const targetSubagentId = toolOutput.subagent_id;
      const existingToolData = refs.current.botMessage?.tool_data ?? [];
      const updatedToolData = updateSubagentInToolData(
        existingToolData,
        targetSubagentId,
        (g) => ({
          ...g,
          tool_calls: g.tool_calls.map((tc) =>
            tc.tool_call_id === toolOutput.tool_call_id
              ? { ...tc, output: toolOutput.output }
              : tc,
          ),
        }),
      );
      updateBotMessage({ tool_data: updatedToolData });

      const conversationId =
        refs.current.newConversation.id ||
        useChatStore.getState().activeConversationId;
      if (refs.current.botMessage?.message_id && conversationId) {
        schedulePersist(conversationId);
      }
      return;
    }

    // Root-level tool_output — not associated with a subagent
    const existingToolData = refs.current.botMessage?.tool_data ?? [];
    const updatedToolData = mergeToolOutputIntoToolData(
      existingToolData,
      toolOutput,
    );

    updateBotMessage({ tool_data: updatedToolData });

    const conversationId =
      refs.current.newConversation.id ||
      useChatStore.getState().activeConversationId;
    if (refs.current.botMessage?.message_id && conversationId) {
      schedulePersist(conversationId);
    }
  };

  const handleSubagentStart = (payload: SubagentStartPayload) => {
    const group: SubagentGroupData = {
      subagent_id: payload.subagent_id,
      subagent_name: payload.subagent_name,
      agent_type: payload.agent_type,
      tool_calls: [],
      duration_ms: null,
      token_count: null,
      started_at: payload.started_at,
      completed_at: null,
      icon_url: payload.icon_url ?? null,
      tool_category: payload.tool_category ?? null,
      nested_subagents: [],
    };

    const existingToolData = refs.current.botMessage?.tool_data ?? [];

    // If this subagent was spawned from within another subagent, nest it inside the parent.
    if (payload.parent_subagent_id) {
      const parentId = payload.parent_subagent_id;
      const updatedToolData = updateSubagentInToolData(
        existingToolData,
        parentId,
        (g) => ({
          ...g,
          nested_subagents: [...g.nested_subagents, group],
        }),
      );
      updateBotMessage({ tool_data: updatedToolData });
    } else {
      const newEntry = {
        tool_name: "subagent_group" as const,
        tool_category: "subagent",
        data: group,
        timestamp: payload.started_at,
      };
      updateBotMessage({ tool_data: [...existingToolData, newEntry] });
    }

    const conversationId =
      refs.current.newConversation.id ||
      useChatStore.getState().activeConversationId;
    if (refs.current.botMessage?.message_id && conversationId) {
      schedulePersist(conversationId);
    }
  };

  const handleSubagentEnd = (payload: SubagentEndPayload) => {
    const existingToolData = refs.current.botMessage?.tool_data ?? [];
    const updatedToolData = updateSubagentInToolData(
      existingToolData,
      payload.subagent_id,
      (g) => ({
        ...g,
        duration_ms: payload.duration_ms ?? null,
        token_count: payload.token_count,
        completed_at: new Date().toISOString(),
      }),
    );

    updateBotMessage({ tool_data: updatedToolData });

    const conversationId =
      refs.current.newConversation.id ||
      useChatStore.getState().activeConversationId;
    if (refs.current.botMessage?.message_id && conversationId) {
      schedulePersist(conversationId);
    }
  };

  const handleTodoProgress = (snapshot: TodoProgressSnapshot) => {
    // Accumulate snapshots keyed by source on the task-progress field
    const existing = refs.current.botMessage?.todo_progress ?? {};
    const source = snapshot.source || "executor";
    const accumulated = {
      ...existing,
      [source]: snapshot,
    };

    const existingToolData = refs.current.botMessage?.tool_data ?? [];
    const updatedToolData = upsertTodoProgressToolData(
      existingToolData,
      snapshot,
    ) as ToolDataEntry[];

    updateBotMessage({
      todo_progress: accumulated,
      tool_data: updatedToolData,
    });

    // Sync to store for live rendering
    const conversationId =
      refs.current.newConversation.id ||
      useChatStore.getState().activeConversationId;
    if (refs.current.botMessage?.message_id && conversationId) {
      schedulePersist(conversationId);
    }
  };

  const handleImageGeneration = (data: Record<string, unknown>) => {
    if (data.status === "generating_image") {
      setLoadingText("Generating image...");
      updateBotMessage({
        image_data: { url: "", prompt: refs.current.userPrompt },
        response: "",
      });
      return true;
    }

    if (data.image_data && typeof data.image_data === "object") {
      updateBotMessage({
        image_data: data.image_data as MessageType["image_data"],
        loading: false,
      });
      return true;
    }

    return false;
  };

  const handleMainResponseComplete = () => {
    setIsLoading(false);
    // The comms agent has finished its initial response ("on it"), so unlock the
    // composer — the user can now queue while any background executor runs.
    useLoadingStore.getState().setMainResponseStreaming(false);
    resetLoadingText();
    updateBotMessage({ loading: false });
  };

  const handleStreamingContent = async (data: Record<string, unknown>) => {
    if (data.response) {
      refs.current.accumulatedResponse += data.response;
    }

    // Skip tool_data, tool_output, and task-progress - they're handled separately
    // to avoid double-processing in parseStreamData
    const {
      tool_data: _toolData,
      tool_output: _toolOutput,
      todo_progress: _todoProgress,
      ...restData
    } = data;
    const streamUpdates = parseStreamData(restData, refs.current.botMessage);

    updateBotMessage({
      ...streamUpdates,
      response: refs.current.accumulatedResponse,
    });

    const conversationId =
      refs.current.newConversation.id ||
      useChatStore.getState().activeConversationId;

    // Update store directly during streaming (no DB writes to avoid race conditions)
    if (refs.current.botMessage?.message_id && conversationId) {
      updateBotMessageInStore(conversationId);
    }
  };

  // Re-show the spinner when an earlier main_response_complete hid it but a
  // later event (executor progress or executor result) means we're still
  // working.
  const ensureSpinnerOn = (): void => {
    if (useLoadingStore.getState().isLoading) return;
    setIsLoading(true);
    updateBotMessage({ loading: true });
  };

  const handleConversationInitialized = async (parsed: {
    conversation_id?: string;
    conversation_description?: string | null;
    bot_message_id?: string;
    user_message_id?: string;
    stream_id?: string;
  }): Promise<void> => {
    if (parsed.conversation_id) {
      await handleNewConversation({
        conversation_id: parsed.conversation_id,
        conversation_description: parsed.conversation_description ?? null,
        bot_message_id: parsed.bot_message_id,
        user_message_id: parsed.user_message_id,
        stream_id: parsed.stream_id,
      });
      return;
    }
    if (
      parsed.user_message_id &&
      parsed.bot_message_id &&
      !refs.current.newConversation.id
    ) {
      await handleExistingConversationMessages({
        user_message_id: parsed.user_message_id,
        bot_message_id: parsed.bot_message_id,
        stream_id: parsed.stream_id,
      });
    }
  };

  const handleConversationDescriptionEvent = (description: string): void => {
    if (!refs.current.newConversation.id) return;
    refs.current.newConversation.description = description;
    handleConversationDescriptionUpdate(
      refs.current.newConversation.id,
      description,
    );
  };

  const handleProgressEvent = (parsed: {
    message: string;
    tool_name?: string;
    tool_category?: string;
  }): void => {
    ensureSpinnerOn();
    setLoadingText(parsed.message, {
      toolName: parsed.tool_name,
      toolCategory: parsed.tool_category,
    });
  };

  const handleResponseChunk = (
    chunk: string,
    streamingData: Record<string, unknown>,
  ): void => {
    ensureSpinnerOn();
    streamingData.response =
      typeof streamingData.response === "string"
        ? `${streamingData.response}${chunk}`
        : chunk;
  };

  // Route a single parsed event to the right handler. Returns a string only for
  // the `error` event — caller treats that as a signal to halt the for-loop and
  // bubble the error back out of handleStreamEvent.
  const dispatchStreamEvent = async (
    parsed: ParsedStreamEvent,
    streamingData: Record<string, unknown>,
  ): Promise<string | undefined> => {
    // Background executor tool/subagent events arrive after `main_response_complete`
    // has hidden the spinner. They mean work is still in progress, so re-show the
    // loading indicator — the same way `progress`/`response` already do. (See
    // ensureSpinnerOn: it was built for exactly this "executor result" case.)
    if (
      parsed.type === "tool_data" ||
      parsed.type === "tool_output" ||
      parsed.type === "subagent_start" ||
      parsed.type === "subagent_end" ||
      parsed.type === "todo_progress"
    ) {
      ensureSpinnerOn();
    }
    switch (parsed.type) {
      case "done":
      case "keepalive":
        return undefined;
      case "error":
        toast.error(parsed.error);
        return parsed.error;
      case "main_response_complete":
        handleMainResponseComplete();
        return undefined;
      case "tool_data":
        handleToolData(parsed.entry as ToolDataEntry);
        return undefined;
      case "tool_output":
        handleToolOutput(parsed.output);
        return undefined;
      case "subagent_start":
        handleSubagentStart(parsed.payload);
        return undefined;
      case "subagent_end":
        handleSubagentEnd(parsed.payload);
        return undefined;
      case "todo_progress":
        handleTodoProgress(parsed.snapshot as TodoProgressSnapshot);
        return undefined;
      case "progress":
        handleProgressEvent(parsed);
        return undefined;
      case "response":
        handleResponseChunk(parsed.chunk, streamingData);
        return undefined;
      case "follow_up_actions":
        streamingData.follow_up_actions = parsed.actions;
        return undefined;
      case "conversation_initialized":
        await handleConversationInitialized(parsed);
        return undefined;
      case "conversation_description":
        handleConversationDescriptionEvent(parsed.description);
        return undefined;
      case "unknown":
        Object.assign(streamingData, parsed.payload);
        return undefined;
    }
    return undefined;
  };

  const handleStreamEvent = async (
    event: EventSourceMessage,
  ): Promise<undefined | string> => {
    if (!streamInProgressRef.current) return "Stream was aborted";
    if (!event.data) return; // Skip empty events (@microsoft/fetch-event-source dispatches these for SSE comments)

    try {
      const parsedEvents = parseChatStreamEvent(event.data);
      const streamingData: Record<string, unknown> = {};
      for (const parsed of parsedEvents) {
        const haltError = await dispatchStreamEvent(parsed, streamingData);
        if (haltError !== undefined) return haltError;
      }
      if (Object.keys(streamingData).length === 0) return;
      if (handleImageGeneration(streamingData)) return;
      await handleStreamingContent(streamingData);
      return undefined;
    } catch (error) {
      return formatStreamError(error, event.data);
    }
  };

  return {
    handleToolData,
    handleToolOutput,
    handleSubagentStart,
    handleSubagentEnd,
    handleTodoProgress,
    handleImageGeneration,
    handleMainResponseComplete,
    handleStreamingContent,
    handleStreamEvent,
  };
};
