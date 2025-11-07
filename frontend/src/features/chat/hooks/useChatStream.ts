import { EventSourceMessage } from "@microsoft/fetch-event-source";
import { redirect } from "next/navigation";
import { useEffect, useRef } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useFetchConversations } from "@/features/chat/hooks/useConversationList";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { streamController } from "@/features/chat/utils/streamController";
import { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import { useComposerStore } from "@/stores/composerStore";
import { MessageType } from "@/types/features/convoTypes";
import { WorkflowData } from "@/types/features/workflowTypes";
import { FileData } from "@/types/shared";
import fetchDate from "@/utils/date/dateUtils";

import { useLoadingText } from "./useLoadingText";
import { parseStreamData } from "./useStreamDataParser";

export const useChatStream = () => {
  const { setIsLoading, setAbortController } = useLoading();
  const { updateConvoMessages, convoMessages } = useConversation();
  const fetchConversations = useFetchConversations();
  const { setLoadingText, resetLoadingText } = useLoadingText();

  // Add ref to track if a stream is already in progress
  const streamInProgressRef = useRef(false);

  // Unified ref storage
  const refs = useRef({
    convoMessages,
    botMessage: null as MessageType | null,
    accumulatedResponse: "",
    userPrompt: "",
    currentStreamingMessages: [] as MessageType[], // Track messages for current streaming session
    newConversation: {
      id: null as string | null,
      description: null as string | null,
    },
  });

  useEffect(() => {
    refs.current.convoMessages = convoMessages;
  }, [convoMessages]);

  // Reset all stream-related state
  const resetStreamState = () => {
    streamInProgressRef.current = false;
    refs.current.botMessage = null;
    refs.current.accumulatedResponse = "";
    refs.current.userPrompt = "";
    refs.current.currentStreamingMessages = [];
    refs.current.newConversation = { id: null, description: null };
    setIsLoading(false);
    resetLoadingText();
    streamController.clear();
    setAbortController(null);
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
        redirect(`/c/${response.conversation_id}`);
      }
    } catch (saveError) {
      console.error("Failed to save incomplete conversation:", saveError);
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

      // Use the streaming messages if available, otherwise fall back to refs
      const currentConvo = [...refs.current.currentStreamingMessages];

      if (
        currentConvo.length > 0 &&
        currentConvo[currentConvo.length - 1].type === "bot"
      ) {
        currentConvo[currentConvo.length - 1] = refs.current.botMessage;
      } else {
        currentConvo.push(refs.current.botMessage);
      }

      updateConvoMessages(currentConvo);
    } catch (error) {
      console.error("Error updating bot message:", error);
    }
  };

  /**
   * Handles the incoming stream event, updating the bot message and loading text.
   * @param event - The EventSourceMessage received from the stream.
   * @returns An error message if an error occurs, otherwise undefined.
   */
  const handleStreamEvent = (event: EventSourceMessage): void | string => {
    try {
      if (event.data === "[DONE]") return;

      const data = JSON.parse(event.data);
      if (data.error) {
        // Immediately terminate the stream on error
        console.error("Stream error received:", data.error);
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
      if (data.conversation_id)
        refs.current.newConversation.id = data.conversation_id;
      if (data.conversation_description)
        refs.current.newConversation.description =
          data.conversation_description;

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

      // Add to the accumulated response if there's new response content
      if (data.response) {
        refs.current.accumulatedResponse += data.response;
      }

      // Parse only the data that's actually present in this stream chunk
      const streamUpdates = parseStreamData(data, refs.current.botMessage);

      updateBotMessage({
        ...streamUpdates,
        response: refs.current.accumulatedResponse,
      });
    } catch (error) {
      console.error("Error handling stream event:", error);
      const errorMessage =
        error instanceof Error ? error.message : "Unknown error";
      return `Error processing stream data: ${errorMessage}`;
    }
  };

  const handleStreamClose = async () => {
    try {
      if (!refs.current.botMessage) return;

      // Create a shallow copy of the current bot message to preserve all existing data
      const preservedBotMessage = { ...refs.current.botMessage };

      // Update only the loading state while preserving everything else
      updateBotMessage({
        ...preservedBotMessage,
        loading: false,
      });

      // Only update loading if it hasn't been set to false already
      // (main_response_complete would have already set it to false)
      setIsLoading(false);
      resetLoadingText();
      streamController.clear();

      // Only navigate for successful completions (manual aborts are handled in the save callback)
      if (refs.current.newConversation.id) {
        // If a new conversation was created, update the URL and fetch conversations
        // Using replaceState to avoid reloading the page that would happen with pushState
        // Reloading results in fetching conversations again hence the flickering
        window.history.replaceState(
          {},
          "",
          `/c/${refs.current.newConversation.id}`,
        );
        fetchConversations();
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
    botMessageId: string,
    fileData: FileData[] = [],
    selectedTool: string | null = null,
    toolCategory: string | null = null,
    selectedWorkflow: WorkflowData | null = null,
    selectedCalendarEvent: SelectedCalendarEventData | null = null,
  ) => {
    try {
      refs.current.accumulatedResponse = "";
      refs.current.userPrompt = inputText;

      // Set up the complete message array for this streaming session
      refs.current.currentStreamingMessages = [
        ...refs.current.convoMessages,
        ...currentMessages,
      ];

      refs.current.botMessage = {
        type: "bot",
        message_id: botMessageId,
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
        undefined, // conversationId is will be fetched from the URL
        handleStreamEvent,
        handleStreamClose,
        handleStreamError, // Use the new error handler
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
    }
  };

  return streamFunction;
};
