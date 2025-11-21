import { EventSourceMessage } from "@microsoft/fetch-event-source";
import { useRouter } from "next/navigation";
import { useRef } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { streamController } from "@/features/chat/utils/streamController";
import { db, type IConversation, type IMessage } from "@/lib/db/chatDb";
import { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import { useChatStore } from "@/stores/chatStore";
import { useComposerStore } from "@/stores/composerStore";
import { MessageType } from "@/types/features/convoTypes";
import { WorkflowData } from "@/types/features/workflowTypes";
import { FileData } from "@/types/shared";
import fetchDate from "@/utils/date/dateUtils";

import { useLoadingText } from "./useLoadingText";
import { parseStreamData } from "./useStreamDataParser";

export const useChatStream = () => {
  const router = useRouter();
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

    // Clear any remaining optimistic message (error/abort scenarios)
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

  const saveIncompleteConversation = async () => {
    if (!refs.current.botMessage || !refs.current.accumulatedResponse) return;

    try {
      const response = await chatApi.saveIncompleteConversation(
        refs.current.userPrompt,
        refs.current.newConversation.id || null,
        refs.current.accumulatedResponse,
        refs.current.botMessage.fileData || [],
        refs.current.botMessage.selectedTool || null,
        refs.current.botMessage.toolCategory || null,
        refs.current.botMessage.selectedWorkflow || null,
        refs.current.botMessage.selectedCalendarEvent || null,
      );

      // Handle navigation for incomplete conversations
      if (response.conversation_id && !refs.current.newConversation.id) {
        router.replace(`/c/${response.conversation_id}`);
      }
    } catch (saveError) {
      console.error("Failed to save incomplete conversation:", saveError);
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
    return {
      id: messageId,
      conversationId,
      content,
      role,
      status,
      createdAt: new Date(),
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
    };
  };

  const handleProgressUpdate = (progressData: any) => {
    if (typeof progressData === "string") {
      setLoadingText(progressData);
    } else if (typeof progressData === "object" && progressData.message) {
      setLoadingText(progressData.message, {
        toolName: progressData.tool_name,
        toolCategory: progressData.tool_category,
      });
    }
  };

  const handleImageGeneration = (data: any) => {
    if (data.status === "generating_image") {
      setLoadingText("Generating image...");
      updateBotMessage({
        image_data: { url: "", prompt: refs.current.userPrompt },
        response: "",
      });
      return true;
    }

    if (data.image_data) {
      updateBotMessage({
        image_data: data.image_data,
        loading: false,
      });
      return true;
    }

    return false;
  };

  const handleMainResponseComplete = () => {
    setIsLoading(false);
    resetLoadingText();
    updateBotMessage({ loading: false });
  };

  const persistUserMessage = async (
    conversationId: string,
    messageId: string,
  ) => {
    if (!refs.current.userMessage || !refs.current.optimisticUserId) return;

    try {
      await db.putMessage(
        createIMessage(
          messageId,
          conversationId,
          refs.current.userMessage.response || "",
          "user",
          "sent",
          refs.current.userMessage,
        ),
      );
      refs.current.userMessage.message_id = messageId;
    } catch (error) {
      console.error("Failed to persist user message:", error);
    }
  };

  const persistBotMessage = async (
    conversationId: string,
    messageId: string,
  ) => {
    if (!refs.current.botMessage) return;

    try {
      // Initial creation in IndexedDB - will trigger event to update store
      await db.putMessage(
        createIMessage(
          messageId,
          conversationId,
          "", // Empty content initially
          "assistant",
          "sending",
          refs.current.botMessage,
        ),
      );
    } catch (error) {
      console.error("Failed to persist initial bot message:", error);
    }
  };

  const handleNewConversation = async (data: any) => {
    const {
      conversation_id,
      conversation_description,
      bot_message_id,
      user_message_id,
    } = data;

    refs.current.newConversation.id = conversation_id;
    refs.current.newConversation.description = conversation_description;

    if (bot_message_id && refs.current.botMessage) {
      refs.current.botMessage.message_id = bot_message_id;
    }

    if (user_message_id && refs.current.userMessage) {
      refs.current.userMessage.message_id = user_message_id;
    }

    await handleConversationCreation(conversation_id, conversation_description);

    if (user_message_id && refs.current.optimisticUserId) {
      await persistUserMessage(conversation_id, user_message_id);
    }

    if (bot_message_id) {
      await persistBotMessage(conversation_id, bot_message_id);
    }

    useChatStore.getState().clearOptimisticMessage();
    window.history.replaceState({}, "", `/c/${conversation_id}`);
    useChatStore.getState().setActiveConversationId(conversation_id);
  };

  const handleExistingConversationMessages = async (data: any) => {
    const { user_message_id, bot_message_id } = data;
    const conversationId = useChatStore.getState().activeConversationId;
    if (!conversationId) return;

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

  const handleStreamingContent = async (data: any) => {
    if (data.response) {
      refs.current.accumulatedResponse += data.response;
    }

    const streamUpdates = parseStreamData(data, refs.current.botMessage);

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

    const updatedMessage: IMessage = {
      id: refs.current.botMessage.message_id,
      conversationId,
      content: refs.current.accumulatedResponse,
      role: "assistant",
      status: "sending",
      createdAt: new Date(),
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
  ): Promise<void | string> => {
    if (!streamInProgressRef.current) {
      return "Stream was aborted";
    }

    try {
      const data = event.data === "[DONE]" ? null : JSON.parse(event.data);
      if (event.data === "[DONE]") return;
      if (data.error) return data.error;

      if (data.main_response_complete) {
        handleMainResponseComplete();
        return;
      }

      if (data.progress) {
        handleProgressUpdate(data.progress);
      }

      if (handleImageGeneration(data)) return;

      if (data.conversation_id) {
        await handleNewConversation(data);
      } else if (
        data.user_message_id &&
        data.bot_message_id &&
        !refs.current.newConversation.id
      ) {
        await handleExistingConversationMessages(data);
      } else if (
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
      if (!refs.current.botMessage) return;

      setIsLoading(false);
      resetLoadingText();
      streamController.clear();

      if (refs.current.botMessage && refs.current.newConversation.id) {
        updateBotMessage({ loading: false });
      }

      // Persist final message state to IndexedDB after stream completion
      if (refs.current.botMessage?.message_id) {
        const conversationId =
          refs.current.newConversation.id ||
          useChatStore.getState().activeConversationId;

        if (conversationId) {
          try {
            // Get the complete message from store to ensure all streamed data is persisted
            const messageFromStore = useChatStore
              .getState()
              .messagesByConversation[
                conversationId
              ]?.find((msg) => msg.id === refs.current.botMessage!.message_id);

            if (messageFromStore) {
              // Persist the complete message with final status
              await db.putMessage({
                ...messageFromStore,
                status: "sent",
                updatedAt: new Date(),
              });
            }

            // Update conversation metadata only when stream ends
            await db.updateConversationFields(conversationId, {
              updatedAt: new Date(),
            });
          } catch (error) {
            console.error("Failed to persist final message:", error);
          }
        }
      }

      // Reset stream state after successful completion
      streamInProgressRef.current = false;
      refs.current.botMessage = null;
      refs.current.currentStreamingMessages = [];
      refs.current.newConversation = { id: null, description: null };
    } catch (error) {
      console.error("Error handling stream close:", error);
      resetStreamState(); // Ensure state is reset even on error
    }
  };

  const handleStreamError = (error: Error) => {
    // Reset stream state immediately
    resetStreamState();

    // Handle non-abort errors
    if (error.name !== "AbortError") {
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
  ) => {
    if (streamInProgressRef.current) {
      return;
    }

    streamInProgressRef.current = true;

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

      // Register the save callback for when user clicks stop
      streamController.setSaveCallback(() => {
        // Update the UI immediately when stop is clicked
        if (refs.current.botMessage) {
          updateBotMessage({
            response: refs.current.accumulatedResponse,
            loading: false,
          });
        }

        // Save the incomplete conversation
        saveIncompleteConversation();
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
      );
    } catch (error) {
      console.error("Error initiating chat stream:", error);
      resetStreamState(); // Reset state on any error
    } finally {
      streamInProgressRef.current = false;
    }
  };

  return streamFunction;
};
