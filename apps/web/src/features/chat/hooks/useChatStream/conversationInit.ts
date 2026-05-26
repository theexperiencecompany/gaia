import { streamController } from "@/features/chat/utils/streamController";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { db, type IConversation, type IMessage } from "@/lib/db/chatDb";
import { streamState } from "@/lib/streamState";
import { useChatStore } from "@/stores/chatStore";
import { createIMessage } from "./messageBuilder";
import type { StreamContext } from "./types";

export const createConversationInitHandlers = (
  ctx: StreamContext,
  persistBotMessage: (
    conversationId: string,
    messageId: string,
  ) => Promise<void>,
) => {
  const { refs } = ctx;

  const handleConversationCreation = async (
    conversationId: string,
    description: string | null,
  ) => {
    console.log(
      "[useChatStream] handleConversationCreation:",
      conversationId,
      description,
    );
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

        // Track new conversation creation
        trackEvent(ANALYTICS_EVENTS.CHAT_CONVERSATION_CREATED, {
          conversationId,
          source: "chat",
        });
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

    console.log(
      "[useChatStream] handleNewConversation:",
      conversation_id,
      "desc:",
      conversation_description,
    );
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

      const botMessageWithDate = {
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

    // CRITICAL: Update the Zustand store SYNCHRONOUSLY first so that
    // useConversation immediately returns messages and subsequent streaming
    // events can render in real-time. DB writes happen in the background.
    if (userIMessage) {
      useChatStore.getState().addOrUpdateMessage(userIMessage);
    }
    if (botIMessage) {
      useChatStore.getState().addOrUpdateMessage(botIMessage);
    }
    useChatStore.getState().clearOptimisticMessage();
    // Don't rewrite the URL when the user isn't on a /c route (e.g. the
    // onboarding flow) — only sync it when already viewing a conversation.
    if (/^\/c(\/|$)/.test(globalThis.location.pathname)) {
      globalThis.history.replaceState({}, "", `/c/${conversation_id}`);
    }
    useChatStore.getState().setActiveConversationId(conversation_id);
    useChatStore.getState().setStreamingConversationId(conversation_id);

    // Persist to IndexedDB in the background — the store already has the data
    // so streaming can proceed while this writes.
    db.persistMessagePair(userIMessage, botIMessage).catch((error) => {
      console.error("Failed to persist message pair:", error);
    });
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

  return {
    handleConversationCreation,
    handleConversationDescriptionUpdate,
    handleNewConversation,
    handleExistingConversationMessages,
  };
};
