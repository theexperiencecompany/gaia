import { EventSourceMessage } from "@microsoft/fetch-event-source";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { streamController } from "@/features/chat/utils/streamController";
import { db, type IMessage, type IConversation } from "@/lib/db/chatDb";
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

  // Generate unique ID for this hook instance
  const hookIdRef = useRef(
    `chatStream-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
  );
  const hookId = hookIdRef.current;

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

  // Cleanup stream on unmount
  useEffect(() => {
    return () => {
      if (streamInProgressRef.current) {
        streamController.triggerSave();
        streamController.abort();
      }
    };
  }, [hookId]);

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
      metadata: {
        originalMessage: sourceMessage,
      },
    };
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

      // Bot message updates are persisted to IndexedDB during streaming
      // Events will propagate to chatStore via event handlers
    } catch (error) {
      console.error("Error updating bot message:", error);
    }
  };

  /**
   * Handles the incoming stream event, updating the bot message and loading text.
   * @param event - The EventSourceMessage received from the stream.
   * @returns An error message if an error occurs, otherwise undefined.
   */
  const handleStreamEvent = async (
    event: EventSourceMessage,
  ): Promise<void | string> => {
    if (!streamInProgressRef.current) {
      return "Stream was aborted";
    }

    try {
      const data = event.data === "[DONE]" ? null : JSON.parse(event.data);
      if (event.data === "[DONE]") {
        return;
      }

      if (data.error) {
        // Immediately terminate the stream on error
        return data.error;
      }

      // Handle main response completion marker
      if (data.main_response_complete) {
        setIsLoading(false); // Stop loading animation immediately
        resetLoadingText(); // Clear any loading text

        // Update the bot message to stop its individual loading state
        updateBotMessage({
          loading: false,
        });

        // Continue processing the stream for follow-up actions
        return;
      }

      if (data.progress) {
        // Handle both old format (string) and new format (object with tool info)
        if (typeof data.progress === "string") {
          setLoadingText(data.progress);
        } else if (typeof data.progress === "object" && data.progress.message) {
          // Enhanced progress with tool information
          setLoadingText(data.progress.message, {
            toolName: data.progress.tool_name,
            toolCategory: data.progress.tool_category,
          });
        }
      }
      if (data.conversation_id) {
        refs.current.newConversation.id = data.conversation_id;
        refs.current.newConversation.description =
          data.conversation_description;

        // Store backend-generated message IDs
        if (data.bot_message_id && refs.current.botMessage) {
          refs.current.botMessage.message_id = data.bot_message_id;
        }

        // Store user message ID
        if (data.user_message_id && refs.current.userMessage) {
          refs.current.userMessage.message_id = data.user_message_id;
        }

        // Update URL and set active conversation ID
        window.history.replaceState({}, "", `/c/${data.conversation_id}`);
        useChatStore.getState().setActiveConversationId(data.conversation_id);

        // Add conversation to store immediately with temporary description
        await handleConversationCreation(
          data.conversation_id,
          data.conversation_description,
        );

        // Persist user message with backend-generated ID for new conversations
        // Replace the optimistic message (with temp conversation ID) with real IDs
        if (
          refs.current.userMessage &&
          data.user_message_id &&
          refs.current.optimisticUserId
        ) {
          try {
            // Delete the optimistic message with temp conversation ID
            await db.replaceOptimisticMessage(
              refs.current.optimisticUserId,
              data.user_message_id,
            );

            // Put the message with real conversation_id and backend user_message_id
            await db.putMessage(
              createIMessage(
                data.user_message_id,
                data.conversation_id,
                refs.current.userMessage.response || "",
                "user",
                "sent",
                refs.current.userMessage,
              ),
            );

            refs.current.userMessage.message_id = data.user_message_id;
            console.log(
              `[New Conversation] Replaced optimistic message with backend ID ${data.user_message_id}`,
            );
          } catch (error) {
            console.error("Failed to replace optimistic user message:", error);
          }
        }

        // Now persist initial bot message with conversation ID
        if (refs.current.botMessage && data.bot_message_id) {
          try {
            await db.putMessage(
              createIMessage(
                data.bot_message_id,
                data.conversation_id,
                "",
                "assistant",
                "sending",
                refs.current.botMessage,
              ),
            );
          } catch (error) {
            console.error("Failed to persist initial bot message:", error);
          }
        }
      } else if (
        data.user_message_id &&
        data.bot_message_id &&
        !refs.current.newConversation.id
      ) {
        // For existing conversations, we receive message IDs in first stream event
        const conversationId = useChatStore.getState().activeConversationId;

        // Replace optimistic user message with backend ID
        if (refs.current.optimisticUserId && conversationId) {
          try {
            await db.replaceOptimisticMessage(
              refs.current.optimisticUserId,
              data.user_message_id,
            );
            if (refs.current.userMessage) {
              refs.current.userMessage.message_id = data.user_message_id;
            }
            console.log(
              `Replaced optimistic ID ${refs.current.optimisticUserId} with backend ID ${data.user_message_id}`,
            );
          } catch (error) {
            console.error("Failed to replace optimistic message:", error);
          }
        }

        // Persist bot message for existing conversation
        if (data.bot_message_id && refs.current.botMessage && conversationId) {
          refs.current.botMessage.message_id = data.bot_message_id;

          try {
            await db.putMessage(
              createIMessage(
                data.bot_message_id,
                conversationId,
                "",
                "assistant",
                "sending",
                refs.current.botMessage,
              ),
            );
          } catch (error) {
            console.error("Failed to persist initial bot message:", error);
          }
        }
      } else if (
        data.conversation_description &&
        refs.current.newConversation.id
      ) {
        // Update the description when it arrives later (after LLM generation)
        refs.current.newConversation.description =
          data.conversation_description;
        handleConversationDescriptionUpdate(
          refs.current.newConversation.id,
          data.conversation_description,
        );
      }

      if (data.status === "generating_image") {
        setLoadingText("Generating image...");
        updateBotMessage({
          image_data: { url: "", prompt: refs.current.userPrompt },
          response: "",
        });
        return;
      }

      if (data.image_data) {
        updateBotMessage({
          image_data: data.image_data,
          loading: false,
        });
        return;
      }

      console.log(refs.current);

      // Add to the accumulated response if there's new response content
      if (data.response) {
        refs.current.accumulatedResponse += data.response;

        // Incrementally persist streaming content (works for both new and existing conversations)
        if (refs.current.botMessage?.message_id) {
          const conversationId =
            refs.current.newConversation.id ||
            useChatStore.getState().activeConversationId;
          if (conversationId) {
            try {
              await db.updateMessageContent(
                refs.current.botMessage.message_id,
                refs.current.accumulatedResponse,
              );
            } catch (error) {
              console.error("Failed to update streaming content:", error);
            }
          }
        }
      }

      // Parse only the data that's actually present in this stream chunk
      const streamUpdates = parseStreamData(data, refs.current.botMessage);

      updateBotMessage({
        ...streamUpdates,
        response: refs.current.accumulatedResponse,
      });
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

      // Only update loading if it hasn't been set to false already
      // (main_response_complete would have already set it to false)
      setIsLoading(false);
      resetLoadingText();
      streamController.clear();

      if (refs.current.botMessage && refs.current.newConversation.id) {
        const botMessageId = refs.current.botMessage.message_id;
        if (!botMessageId) return;

        // Mark message as complete in database (message already exists from initial persistence)
        try {
          await db.updateMessageStatus(botMessageId, "sent");
        } catch (error) {
          console.error("Failed to mark bot message as sent:", error);
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
