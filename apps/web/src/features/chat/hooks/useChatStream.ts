import type { EventSourceMessage } from "@microsoft/fetch-event-source";
import { useRef } from "react";
import { toast } from "sonner";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { streamController } from "@/features/chat/utils/streamController";
import { db, type IConversation, type IMessage } from "@/lib/db/chatDb";
import { streamState } from "@/lib/streamState";
import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import { useChatStore } from "@/stores/chatStore";
import { useComposerStore } from "@/stores/composerStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared";
import fetchDate from "@/utils/date/dateUtils";

import { useLoadingText } from "./useLoadingText";
import { parseStreamData } from "./useStreamDataParser";

export const useChatStream = () => {
  const { setIsLoading, setAbortController } = useLoading();
  const { convoMessages } = useConversation();
  const { setLoadingText, resetLoadingText } = useLoadingText();

  // Add ref to track if a stream is already in progress
  const streamInProgressRef = useRef(false);

  // Unified ref storage
  const refs = useRef({
    convoMessages,
    botMessage: null as MessageType | null,
    userMessage: null as MessageType | null,
    optimisticUserId: null as string | null,
    accumulatedResponse: "",
    userPrompt: "",
    currentStreamingMessages: [] as MessageType[], // Track messages for current streaming session
    newConversation: {
      id: null as string | null,
      description: null as string | null,
    },
  });

  // Reset all stream-related state
  const resetStreamState = () => {
    streamState.endStream();

    streamInProgressRef.current = false;
    refs.current.botMessage = null;
    refs.current.userMessage = null;
    refs.current.optimisticUserId = null;
    refs.current.accumulatedResponse = "";
    refs.current.userPrompt = "";
    refs.current.currentStreamingMessages = [];
    refs.current.newConversation = { id: null, description: null };
    setIsLoading(false);
    resetLoadingText();
    streamController.clear();
    setAbortController(null);

    // Clear streaming indicator and any remaining optimistic message
    useChatStore.getState().setStreamingConversationId(null);
    useChatStore.getState().clearOptimisticMessage();
  };

  const handleConversationCreation = async (
    conversationId: string,
    description: string | null,
  ) => {
    // Check if conversation already exists in store
    const existing = useChatStore
      .getState()
      .conversations.find((c) => c.id === conversationId);

    if (!existing) {
      const finalDescription = description || "New Chat";

      // Write to IndexedDB - event will update chatStore
      const newConversation: IConversation = {
        id: conversationId,
        title: finalDescription,
        description: finalDescription,
        starred: false,
        isSystemGenerated: false,
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      try {
        await db.putConversation(newConversation);
      } catch (error) {
        console.error("Failed to save conversation to IndexedDB:", error);
      }
    }
  };

  const handleConversationDescriptionUpdate = async (
    conversationId: string,
    description: string,
  ) => {
    // Update via IndexedDB atomically - event will update Zustand store
    try {
      await db.updateConversationFields(conversationId, {
        description: description,
        title: description,
      });
    } catch (error) {
      console.error("Failed to update conversation description:", error);
    }
  };

  const createIMessage = (
    messageId: string,
    conversationId: string,
    content: string,
    role: "user" | "assistant",
    status: IMessage["status"],
    sourceMessage: MessageType,
  ): IMessage => {
    // Preserve original timestamp from sourceMessage to maintain correct ordering
    // This is critical: messages must be ordered by their creation time, not persist time
    const createdAt = sourceMessage.date
      ? new Date(sourceMessage.date)
      : new Date();

    return {
      id: messageId,
      conversationId,
      content,
      role,
      status,
      createdAt,
      updatedAt: new Date(),
      messageId,
      fileIds: sourceMessage.fileIds,
      fileData: sourceMessage.fileData,
      toolName: sourceMessage.selectedTool ?? null,
      toolCategory: sourceMessage.toolCategory ?? null,
      workflowId: sourceMessage.selectedWorkflow?.id ?? null,
      selectedWorkflow: sourceMessage.selectedWorkflow ?? null,
      selectedCalendarEvent: sourceMessage.selectedCalendarEvent ?? null,
      tool_data: sourceMessage.tool_data ?? null,
      follow_up_actions: sourceMessage.follow_up_actions ?? null,
      image_data: sourceMessage.image_data ?? null,
      memory_data: sourceMessage.memory_data ?? null,
      pinned: sourceMessage.pinned ?? false,
      isConvoSystemGenerated: sourceMessage.isConvoSystemGenerated ?? false,
      replyToMessageId: sourceMessage.replyToMessage?.id ?? null,
      replyToMessageData: sourceMessage.replyToMessage ?? null,
    };
  };

  const handleToolData = (toolData: ToolDataEntry) => {
    // Append tool_data entry to botMessage.tool_data
    const existingToolData = refs.current.botMessage?.tool_data ?? [];
    updateBotMessage({
      tool_data: [...existingToolData, toolData],
    });

    // Extract loading text from tool_data.data.message for UI indicator
    if (
      toolData.tool_name === "tool_calls_data" &&
      typeof toolData.data === "object" &&
      toolData.data !== null
    ) {
      const data = toolData.data as Record<string, unknown>;
      if (data.message && typeof data.message === "string") {
        setLoadingText(data.message, {
          toolName: data.tool_name as string | undefined,
          toolCategory: data.tool_category as string | undefined,
          integrationName: data.integration_name as string | undefined,
          iconUrl: data.icon_url as string | undefined,
          showCategory: (data.show_category as boolean) ?? true,
        });
      }
    }

    // Sync to store for persistence
    const conversationId =
      refs.current.newConversation.id ||
      useChatStore.getState().activeConversationId;
    if (refs.current.botMessage?.message_id && conversationId) {
      updateBotMessageInStore(conversationId);
    }
  };

  /**
   * Helper to update tool_data entries by tool_call_id.
   * Used by handleToolOutput to add output to existing entries.
   */
  const updateToolDataEntry = (
    toolCallId: string,
    updateFn: (data: Record<string, unknown>) => Record<string, unknown>,
  ) => {
    const existingToolData = refs.current.botMessage?.tool_data ?? [];
    const updatedToolData = existingToolData.map((entry): ToolDataEntry => {
      // Only update entries that:
      // 1. Have tool_name === "tool_calls_data"
      // 2. Have a valid data object with a matching tool_call_id
      if (entry.tool_name === "tool_calls_data") {
        const data = entry.data as Record<string, unknown>;
        // Validate that the entry has a tool_call_id and it matches
        if (
          data &&
          typeof data === "object" &&
          "tool_call_id" in data &&
          data.tool_call_id === toolCallId
        ) {
          return {
            ...entry,
            data: updateFn(data) as ToolDataEntry["data"],
          };
        }
      }
      return entry;
    });

    updateBotMessage({
      tool_data: updatedToolData,
    });

    // Sync to store for persistence
    const conversationId =
      refs.current.newConversation.id ||
      useChatStore.getState().activeConversationId;
    if (refs.current.botMessage?.message_id && conversationId) {
      updateBotMessageInStore(conversationId);
    }
  };

  const handleToolOutput = (toolOutput: {
    tool_call_id: string;
    output: string;
  }) => {
    updateToolDataEntry(toolOutput.tool_call_id, (data) => ({
      ...data,
      output: toolOutput.output,
    }));
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
    console.log("[handleMainResponseComplete] Setting isLoading to false");
    setIsLoading(false);
    resetLoadingText();
    updateBotMessage({ loading: false });
  };

  const persistBotMessage = async (
    conversationId: string,
    messageId: string,
  ) => {
    if (!refs.current.botMessage) return;

    try {
      // Ensure bot message timestamp is AFTER user message for correct ordering
      // Get user message timestamp and add 1ms offset
      const userMessageDate = refs.current.userMessage?.date
        ? new Date(refs.current.userMessage.date)
        : new Date();
      const botMessageDate = new Date(userMessageDate.getTime() + 1);

      // Create a copy of botMessage with the corrected date
      const botMessageWithDate: MessageType = {
        ...refs.current.botMessage,
        date: botMessageDate.toISOString(),
      };

      await db.putMessage(
        createIMessage(
          messageId,
          conversationId,
          "", // Empty content initially
          "assistant",
          "sending",
          botMessageWithDate,
        ),
      );
    } catch (error) {
      console.error("Failed to persist initial bot message:", error);
    }
  };

  const handleNewConversation = async (data: {
    conversation_id: string;
    conversation_description: string | null;
    bot_message_id?: string;
    user_message_id?: string;
    stream_id?: string;
  }) => {
    const {
      conversation_id,
      conversation_description,
      bot_message_id,
      user_message_id,
      stream_id,
    } = data;

    refs.current.newConversation.id = conversation_id;
    refs.current.newConversation.description = conversation_description;

    // Set stream_id for backend cancellation support
    if (stream_id) {
      streamController.setStreamId(stream_id);
    }

    // CRITICAL: Update streamState with the new conversationId for sync protection
    // This prevents background sync from syncing this conversation while it's being streamed
    streamState.updateStreamConversationId(conversation_id);

    if (bot_message_id && refs.current.botMessage) {
      refs.current.botMessage.message_id = bot_message_id;
    }

    if (user_message_id && refs.current.userMessage) {
      refs.current.userMessage.message_id = user_message_id;
    }

    await handleConversationCreation(conversation_id, conversation_description);

    // Create IMessage objects for atomic persistence
    let userIMessage: IMessage | null = null;
    let botIMessage: IMessage | null = null;

    if (
      user_message_id &&
      refs.current.optimisticUserId &&
      refs.current.userMessage
    ) {
      userIMessage = createIMessage(
        user_message_id,
        conversation_id,
        refs.current.userMessage.response || "",
        "user",
        "sent",
        refs.current.userMessage,
      );
      refs.current.userMessage.message_id = user_message_id;
    }

    if (bot_message_id && refs.current.botMessage) {
      // Ensure bot message timestamp is AFTER user message for correct ordering
      const userMessageDate = userIMessage?.createdAt ?? new Date();
      const botMessageDate = new Date(userMessageDate.getTime() + 1);

      const botMessageWithDate: MessageType = {
        ...refs.current.botMessage,
        date: botMessageDate.toISOString(),
      };

      botIMessage = createIMessage(
        bot_message_id,
        conversation_id,
        "",
        "assistant",
        "sending",
        botMessageWithDate,
      );
    }

    // Atomically persist both messages in a single transaction
    // Events are emitted by persistMessagePair to update the store
    try {
      await db.persistMessagePair(userIMessage, botIMessage);
    } catch (error) {
      console.error("Failed to persist message pair:", error);
      // On persistence failure, clear optimistic UI and abort
      useChatStore.getState().clearOptimisticMessage();
      return;
    }

    // Clear optimistic message now that real messages are in the store via events
    useChatStore.getState().clearOptimisticMessage();
    window.history.replaceState({}, "", `/c/${conversation_id}`);
    useChatStore.getState().setActiveConversationId(conversation_id);

    // Set streaming indicator for sidebar
    useChatStore.getState().setStreamingConversationId(conversation_id);
  };

  const handleExistingConversationMessages = async (data: {
    user_message_id: string;
    bot_message_id: string;
    stream_id?: string;
  }) => {
    const { user_message_id, bot_message_id, stream_id } = data;
    const conversationId = useChatStore.getState().activeConversationId;
    if (!conversationId) return;

    // Set stream_id for backend cancellation support
    if (stream_id) {
      streamController.setStreamId(stream_id);
    }

    // Set streaming indicator for sidebar (existing conversation)
    useChatStore.getState().setStreamingConversationId(conversationId);

    if (refs.current.optimisticUserId) {
      try {
        await db.replaceOptimisticMessage(
          refs.current.optimisticUserId,
          user_message_id,
        );
        if (refs.current.userMessage) {
          refs.current.userMessage.message_id = user_message_id;
        }
        await db.updateMessageStatus(user_message_id, "sent");
      } catch (error) {
        console.error("Failed to replace optimistic message:", error);
      }
    }

    if (bot_message_id && refs.current.botMessage) {
      refs.current.botMessage.message_id = bot_message_id;
      await persistBotMessage(conversationId, bot_message_id);
    }
  };

  const handleStreamingContent = async (data: Record<string, unknown>) => {
    if (data.response) {
      refs.current.accumulatedResponse += data.response;
    }

    // Skip tool_data and tool_output - they're handled separately
    // to avoid double-processing in parseStreamData
    const { tool_data: _, tool_output: __, ...restData } = data;
    const streamUpdates = parseStreamData(
      restData as Partial<MessageType>,
      refs.current.botMessage,
    );

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

  const updateBotMessage = (overrides: Partial<MessageType>) => {
    try {
      const baseMessage: MessageType = {
        type: "bot",
        message_id: refs.current.botMessage?.message_id || "",
        response: refs.current.accumulatedResponse,
        date: fetchDate(),
        isConvoSystemGenerated: false,
        loading: true,
      };

      // Preserve existing data and merge with new overrides
      refs.current.botMessage = {
        ...baseMessage,
        ...refs.current.botMessage, // Keep existing data
        ...overrides, // Apply new updates
      };
    } catch (error) {
      console.error("Error updating bot message:", error);
    }
  };

  const updateBotMessageInStore = (conversationId: string) => {
    if (!refs.current.botMessage?.message_id) return;

    // Get existing message to preserve createdAt timestamp
    const state = useChatStore.getState();
    const existingMessages = state.messagesByConversation[conversationId] ?? [];
    const existingMessage = existingMessages.find(
      (m) => m.id === refs.current.botMessage?.message_id,
    );

    // Use existing createdAt, or derive from user message + 1ms offset for correct ordering
    let createdAt: Date;
    if (existingMessage?.createdAt) {
      createdAt = existingMessage.createdAt;
    } else if (refs.current.userMessage?.date) {
      // Bot message should be after user message
      createdAt = new Date(
        new Date(refs.current.userMessage.date).getTime() + 1,
      );
    } else if (refs.current.botMessage.date) {
      createdAt = new Date(refs.current.botMessage.date);
    } else {
      createdAt = new Date();
    }

    const updatedMessage: IMessage = {
      id: refs.current.botMessage.message_id,
      conversationId,
      content: refs.current.accumulatedResponse,
      role: "assistant",
      status: "sending",
      createdAt,
      updatedAt: new Date(),
      messageId: refs.current.botMessage.message_id,
      fileIds: refs.current.botMessage.fileIds,
      fileData: refs.current.botMessage.fileData,
      toolName: refs.current.botMessage.selectedTool ?? null,
      toolCategory: refs.current.botMessage.toolCategory ?? null,
      workflowId: refs.current.botMessage.selectedWorkflow?.id ?? null,
      selectedWorkflow: refs.current.botMessage.selectedWorkflow ?? null,
      selectedCalendarEvent:
        refs.current.botMessage.selectedCalendarEvent ?? null,
      tool_data: refs.current.botMessage.tool_data ?? null,
      follow_up_actions: refs.current.botMessage.follow_up_actions ?? null,
      image_data: refs.current.botMessage.image_data ?? null,
      memory_data: refs.current.botMessage.memory_data ?? null,
      pinned: refs.current.botMessage.pinned ?? false,
      isConvoSystemGenerated:
        refs.current.botMessage.isConvoSystemGenerated ?? false,
    };

    // Update store directly without DB write during streaming
    useChatStore.getState().addOrUpdateMessage(updatedMessage);
  };

  const handleStreamEvent = async (
    event: EventSourceMessage,
  ): Promise<undefined | string> => {
    if (!streamInProgressRef.current) {
      return "Stream was aborted";
    }

    try {
      const data = event.data === "[DONE]" ? null : JSON.parse(event.data);
      if (event.data === "[DONE]") return;
      if (data.error) return data.error;

      if (data.main_response_complete) {
        console.log("[handleStreamEvent] Received main_response_complete");
        handleMainResponseComplete();
        return;
      }

      // Handle tool_data events (tool calls with complete inputs)
      if (data.tool_data) handleToolData(data.tool_data);

      // Handle tool_output events (tool execution results)
      if (data.tool_output) handleToolOutput(data.tool_output);

      if (handleImageGeneration(data)) return;

      if (data.conversation_id) {
        await handleNewConversation(data);
      } else if (
        data.user_message_id &&
        data.bot_message_id &&
        !refs.current.newConversation.id
      )
        await handleExistingConversationMessages(data);
      else if (
        data.conversation_description &&
        refs.current.newConversation.id
      ) {
        refs.current.newConversation.description =
          data.conversation_description;
        handleConversationDescriptionUpdate(
          refs.current.newConversation.id,
          data.conversation_description,
        );
      }

      await handleStreamingContent(data);
    } catch (error) {
      console.error("[useChatStream] Error handling stream event:", {
        error,
        errorMessage: error instanceof Error ? error.message : "Unknown error",
        stack: error instanceof Error ? error.stack : undefined,
        eventData: event.data,
      });
      const errorMessage =
        error instanceof Error ? error.message : "Unknown error";
      return `Error processing stream data: ${errorMessage}`;
    }
  };

  const handleStreamClose = async () => {
    try {
      if (!refs.current.botMessage?.message_id) {
        // No valid bot message to persist - this can happen if stream closes
        // before backend sends message IDs. Still need to fully reset state!
        console.warn(
          "[handleStreamClose] No bot message ID - resetting state without persistence",
        );
        setIsLoading(false);
        resetLoadingText();
        streamController.clear();
        streamState.endStream();
        streamInProgressRef.current = false;
        refs.current.botMessage = null;
        refs.current.currentStreamingMessages = [];
        refs.current.newConversation = { id: null, description: null };
        useChatStore.getState().setStreamingConversationId(null);
        return;
      }

      setIsLoading(false);
      resetLoadingText();
      streamController.clear();

      updateBotMessage({ loading: false });

      const conversationId =
        refs.current.newConversation.id ||
        useChatStore.getState().activeConversationId;

      console.log("[handleStreamClose] Persisting bot message:", {
        hasConversationId: !!conversationId,
        conversationId,
        botMessageId: refs.current.botMessage.message_id,
        responseLength: refs.current.accumulatedResponse.length,
      });

      if (conversationId) {
        try {
          // Use refs.current.botMessage directly as single source of truth
          const finalMessage = createIMessage(
            refs.current.botMessage.message_id,
            conversationId,
            refs.current.accumulatedResponse,
            "assistant",
            "sent",
            refs.current.botMessage,
          );

          // Persist the complete message with final status
          // Event emission will automatically update the store
          await db.putMessage(finalMessage);
          console.log(
            "[handleStreamClose] Bot message persisted successfully:",
            finalMessage.id,
          );

          // Update conversation metadata only when stream ends
          await db.updateConversationFields(conversationId, {
            updatedAt: new Date(),
          });
        } catch (error) {
          console.error("Failed to persist final message:", error);
        }
      } else {
        console.warn(
          "[handleStreamClose] No conversation ID - message not persisted!",
        );
      }

      // CRITICAL: End stream state AFTER all persistence is done
      // This prevents sync from running and overwriting messages during persistence
      streamState.endStream();

      // Reset stream state after successful completion
      streamInProgressRef.current = false;
      refs.current.botMessage = null;
      refs.current.currentStreamingMessages = [];
      refs.current.newConversation = { id: null, description: null };

      // Clear streaming indicator
      useChatStore.getState().setStreamingConversationId(null);
    } catch (error) {
      console.error("Error handling stream close:", error);
      streamState.endStream();
      resetStreamState(); // Ensure state is reset even on error
    }
  };

  const handleStreamError = (error: Error) => {
    // Reset stream state immediately
    resetStreamState();

    // Handle non-abort errors
    if (error.name !== "AbortError") {
      // Show error toast for transparency
      toast.error(
        error.message || "An error occurred while processing your message",
      );

      // Save the user's input text for restoration on error
      if (refs.current.userPrompt) {
        useComposerStore.getState().setInputText(refs.current.userPrompt);
      }
    }
  };

  const streamFunction = async (
    inputText: string,
    currentMessages: MessageType[],
    fileData: FileData[] = [],
    selectedTool: string | null = null,
    toolCategory: string | null = null,
    selectedWorkflow: WorkflowData | null = null,
    selectedCalendarEvent: SelectedCalendarEventData | null = null,
    optimisticUserId?: string,
    replyToMessage: {
      id: string;
      content: string;
      role: "user" | "assistant";
    } | null = null,
  ) => {
    if (streamInProgressRef.current) {
      return;
    }

    streamInProgressRef.current = true;

    // Set global stream state with conversation ID for sync protection
    const conversationId =
      useChatStore.getState().activeConversationId ||
      refs.current.newConversation.id;
    streamState.startStream(conversationId);

    try {
      refs.current.accumulatedResponse = "";
      refs.current.userPrompt = inputText;

      // Set up the complete message array for this streaming session
      refs.current.currentStreamingMessages = [
        ...refs.current.convoMessages,
        ...currentMessages,
      ];

      // Store user message and optimistic ID for later replacement
      refs.current.userMessage =
        currentMessages.find((m) => m.type === "user") || null;
      refs.current.optimisticUserId = optimisticUserId || null;

      resetLoadingText();

      refs.current.botMessage = {
        type: "bot",
        message_id: "", // Will be set by backend
        response: "",
        date: fetchDate(),
        loading: true,
        fileIds: fileData.map((f) => f.fileId),
        fileData,
        selectedTool,
        toolCategory,
        selectedWorkflow,
        selectedCalendarEvent,
      };

      // User and bot message IDs and initial persistence will happen after receiving IDs from backend

      // Create abort controller for this stream
      const controller = new AbortController();
      setAbortController(controller);

      // Register the stop callback for when user clicks stop
      // This persists the current accumulated response to Dexie immediately
      streamController.setSaveCallback(async () => {
        // Set pending save flag to block sync operations during save
        streamState.setPendingSave(true);

        try {
          // Update the UI immediately when stop is clicked
          if (refs.current.botMessage) {
            updateBotMessage({
              response: refs.current.accumulatedResponse,
              loading: false,
            });

            // Persist accumulated response to Dexie using atomic merge-update
            // This preserves existing metadata (tool_data, follow_up_actions, image_data, etc.)
            const conversationId =
              refs.current.newConversation.id ||
              useChatStore.getState().activeConversationId;

            if (conversationId && refs.current.botMessage.message_id) {
              // Use updateMessage for atomic merge-update instead of putMessage
              // This only updates content/status/updatedAt while preserving all other fields
              await db.updateMessage(refs.current.botMessage.message_id, {
                content: refs.current.accumulatedResponse,
                status: "sent",
              });
            }
          }
        } catch (error) {
          console.error("Failed to persist message on abort:", error);
        } finally {
          // Clear pending save flag after save completes
          streamState.setPendingSave(false);
        }
        // Note: Backend also saves - streamController.abort() schedules sync after 3s
      });

      await chatApi.fetchChatStream(
        inputText,
        [...refs.current.convoMessages, ...currentMessages],
        undefined, // conversationId will be fetched from the URL
        handleStreamEvent,
        handleStreamClose,
        handleStreamError,
        fileData,
        selectedTool,
        toolCategory,
        controller,
        selectedWorkflow,
        selectedCalendarEvent,
        replyToMessage,
      );
    } catch (error) {
      console.error("Error initiating chat stream:", error);
      resetStreamState(); // Reset state on any error
    } finally {
      streamInProgressRef.current = false;
      streamState.endStream();
    }
  };

  return streamFunction;
};
