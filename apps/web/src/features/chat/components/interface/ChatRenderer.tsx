"use client";

import { AnimatePresence } from "motion/react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import CreatedByGAIABanner from "@/features/chat/components/banners/CreatedByGAIABanner";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import SearchedImageDialog from "@/features/chat/components/bubbles/bot/SearchedImageDialog";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import GeneratedImageSheet from "@/features/chat/components/image/GeneratedImageSheet";
import { LoadingIndicator } from "@/features/chat/components/interface/LoadingIndicator";
import MemoryModal from "@/features/chat/components/memory/MemoryModal";
import { WelcomeChat } from "@/features/chat/components/welcome/WelcomeChat";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useConversationList } from "@/features/chat/hooks/useConversationList";
import { useLoading } from "@/features/chat/hooks/useLoading";
import { useLoadingText } from "@/features/chat/hooks/useLoadingText";
import { useRetryMessage } from "@/features/chat/hooks/useRetryMessage";
import {
  filterEmptyMessagePairs,
  isBotMessageEmpty,
} from "@/features/chat/utils/messageContentUtils";
import { getMessageProps } from "@/features/chat/utils/messagePropsUtils";
import { useChatStore } from "@/stores/chatStore";
import type {
  ChatBubbleBotProps,
  ChatBubbleUserProps,
  SetImageDataType,
} from "@/types/features/chatBubbleTypes";
import type { MessageType } from "@/types/features/convoTypes";

interface ChatRendererProps {
  convoMessages?: MessageType[];
}

export default function ChatRenderer({
  convoMessages: propConvoMessages,
}: ChatRendererProps) {
  const { convoMessages: storeConvoMessages } = useConversation();
  const convoMessages = propConvoMessages ?? storeConvoMessages;
  const { conversations } = useConversationList();
  const [openGeneratedImage, setOpenGeneratedImage] = useState<boolean>(false);
  const [openMemoryModal, setOpenMemoryModal] = useState<boolean>(false);
  const { isLoading } = useLoading();
  const { loadingText, loadingTextKey, toolInfo } = useLoadingText();
  const { id: convoIdParam } = useParams<{ id: string }>();
  const streamingConversationId = useChatStore(
    (state) => state.streamingConversationId,
  );
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  const executorPendingConversationId = useChatStore(
    (state) => state.executorPendingConversationId,
  );
  // While this conversation is "in progress", suppress follow-up actions and
  // the hover action/timestamp row — they belong to a *finished* turn. A turn
  // is in progress while its SSE stream runs (including the executor phase) AND,
  // for turns that delegated to a background executor, until that executor's
  // result message arrives via WebSocket (a few seconds after SSE close).
  //
  // NB: compare against the store's `activeConversationId`, not the route param
  // — new conversations rewrite the URL via `history.replaceState`, which does
  // not update Next's `useParams`, so `convoIdParam` is stale during streaming.
  const isAwaitingExecutorResult =
    !!executorPendingConversationId &&
    executorPendingConversationId === activeConversationId;
  const isConversationStreaming =
    (!!streamingConversationId &&
      streamingConversationId === activeConversationId) ||
    isAwaitingExecutorResult;
  // The conversation is "working" while the bottom loading indicator is visible
  // (`isLoading || awaiting`) or its SSE stream runs. This is used to suppress
  // the follow-ups + action row on the *active turn's* bubble only (see
  // `suppressForBusy` below) — finished turns above it keep their follow-ups.
  const isConversationBusy = isConversationStreaming || isLoading;
  const scrolledToMessageRef = useRef<string | null>(null);
  const { retryMessage, isRetrying } = useRetryMessage();
  const [imageData, setImageData] = useState<SetImageDataType>({
    src: "",
    prompt: "",
    improvedPrompt: "",
  });

  const conversation = useMemo(() => {
    return conversations.find(
      (convo) => convo.conversation_id === convoIdParam,
    );
  }, [conversations, convoIdParam]);

  // Read off the conversation, not userStore, to avoid a stale-rehydrate race.
  const isWelcomeConversation =
    conversation?.is_onboarding_conversation === true;

  // Handle retry callback
  const handleRetry = useCallback(
    (msgId: string) => {
      if (!convoIdParam) return;
      retryMessage(convoIdParam, msgId);
    },
    [convoIdParam, retryMessage],
  );

  // Create options object for getMessageProps
  const messagePropsOptions = useMemo(
    () => ({
      conversation: conversation
        ? {
            is_system_generated: conversation.is_system_generated,
            system_purpose: conversation.system_purpose ?? undefined,
          }
        : undefined,
      setImageData,
      setOpenGeneratedImage,
      setOpenMemoryModal,
      onRetry: handleRetry,
      isRetrying,
    }),
    [conversation, handleRetry, isRetrying],
  );

  // Filter out empty message pairs
  const filteredMessages = useMemo(() => {
    if (!convoMessages) return [];

    return filterEmptyMessagePairs(
      convoMessages,
      conversation?.is_system_generated || false,
      conversation?.system_purpose ?? undefined,
    );
  }, [
    convoMessages,
    conversation?.is_system_generated,
    conversation?.system_purpose,
  ]);

  // Deduplicate tool calls across all messages in the conversation
  const messagesWithDeduplicatedToolCalls = useMemo(() => {
    const seenToolCallIds = new Set<string>();

    return filteredMessages.map((message) => {
      // Only process bot messages with tool_data
      if (message.type !== "bot" || !message.tool_data) {
        return message;
      }

      // Filter out tool calls that have already been shown in previous messages
      const deduplicatedToolData = message.tool_data
        .map((entry) => {
          // Only deduplicate tool_calls_data entries
          if (entry.tool_name !== "tool_calls_data") {
            return entry;
          }

          // Filter the tool calls array within this entry
          // Cast to unknown[] since we know tool_calls_data contains objects with tool_call_id
          const toolCallsArray = (
            Array.isArray(entry.data) ? entry.data : [entry.data]
          ) as Array<{ tool_call_id?: string }>;
          const filteredCalls = toolCallsArray.filter((call) => {
            const toolCallId = call?.tool_call_id;
            if (!toolCallId) return true; // Keep calls without IDs
            if (seenToolCallIds.has(toolCallId)) return false; // Skip duplicates
            seenToolCallIds.add(toolCallId);
            return true;
          });

          // If all calls were filtered out, return null to remove this entry
          if (filteredCalls.length === 0) return null;

          // Return the entry with filtered calls
          return {
            ...entry,
            data: filteredCalls,
          };
        })
        .filter((entry) => entry !== null);

      return {
        ...message,
        tool_data: deduplicatedToolData,
      } as MessageType;
    });
  }, [filteredMessages]);

  useEffect(() => {
    const messageId = new URLSearchParams(window.location.search).get(
      "messageId",
    );
    if (
      messageId &&
      messagesWithDeduplicatedToolCalls.length > 0 &&
      scrolledToMessageRef.current !== messageId
    ) {
      scrollToMessage(messageId);
      scrolledToMessageRef.current = messageId;
    }
  }, [messagesWithDeduplicatedToolCalls]);

  // A bot message only renders a visible bubble when it is non-empty. Empty bot
  // messages are skipped, so grouping must look ahead past them to the next
  // *rendered* bot bubble — otherwise the last visible bubble wrongly loses its
  // avatar/timestamp/follow-up actions when followed by an empty bot message.
  const rendersAsBotBubble = useCallback(
    (message: MessageType | undefined): boolean => {
      if (!message || message.type !== "bot") return false;
      const props = getMessageProps(message, "bot", messagePropsOptions);
      return !!props && !isBotMessageEmpty(props as ChatBubbleBotProps);
    },
    [messagePropsOptions],
  );

  // The busy/streaming suppression of follow-ups + the action row applies only
  // to the turn that is *currently in progress* — i.e. the last rendered bubble,
  // the one sitting directly above the loading indicator. Earlier, finished
  // turns keep their follow-ups even after a new message starts streaming.
  const lastRenderedIndex = useMemo(() => {
    for (let i = messagesWithDeduplicatedToolCalls.length - 1; i >= 0; i--) {
      const candidate = messagesWithDeduplicatedToolCalls[i];
      if (candidate.type === "bot") {
        if (rendersAsBotBubble(candidate)) return i;
        continue; // empty bot message — never renders, keep scanning back
      }
      return i; // user messages always render
    }
    return -1;
  }, [messagesWithDeduplicatedToolCalls, rendersAsBotBubble]);

  // Walk in `step` direction from `index`, skipping empty bot messages, and
  // report whether the next/previous *rendered* bubble is a bot bubble.
  const hasRenderedBotInDirection = useCallback(
    (index: number, step: 1 | -1): boolean => {
      for (
        let i = index + step;
        i >= 0 && i < messagesWithDeduplicatedToolCalls.length;
        i += step
      ) {
        const candidate = messagesWithDeduplicatedToolCalls[i];
        if (candidate.type !== "bot") return false;
        if (rendersAsBotBubble(candidate)) return true;
        // Empty bot message — skip it and keep scanning in this direction.
      }
      return false;
    },
    [messagesWithDeduplicatedToolCalls, rendersAsBotBubble],
  );

  const scrollToMessage = (messageId: string) => {
    if (!messageId) return;

    const messageElement = document.getElementById(messageId);

    if (!messageElement) return;

    messageElement.scrollIntoView({ behavior: "smooth", block: "start" });
    messageElement.style.transition = "all 0.3s ease";

    setTimeout(() => {
      messageElement.style.scale = "1.07";

      setTimeout(() => {
        messageElement.style.scale = "1";
      }, 300);
    }, 700);
  };

  return (
    <>
      <title id="chat_title">{`${conversations.find((convo) => convo.conversation_id === convoIdParam)?.description || "New chat"} | GAIA`}</title>
      <GeneratedImageSheet
        imageData={imageData}
        openImage={openGeneratedImage}
        setOpenImage={setOpenGeneratedImage}
      />
      <MemoryModal
        isOpen={openMemoryModal}
        onClose={() => setOpenMemoryModal(false)}
      />
      <SearchedImageDialog />
      <CreatedByGAIABanner show={conversation?.is_system_generated === true} />
      {isWelcomeConversation && <WelcomeChat />}
      {messagesWithDeduplicatedToolCalls?.map(
        (message: MessageType, index: number) => {
          let messageProps: ChatBubbleBotProps | ChatBubbleUserProps | null =
            null;

          if (message.type === "bot")
            messageProps = getMessageProps(message, "bot", messagePropsOptions);
          else if (message.type === "user")
            messageProps = getMessageProps(
              message,
              "user",
              messagePropsOptions,
            );

          if (!messageProps) return null;

          // Consecutive bot bubble grouping (iMessage-style):
          // - Only the LAST bot message in a consecutive group shows the avatar
          // - No actions/timestamps/follow-ups on non-last messages
          // - Tight spacing (no gap) between grouped messages
          // Look ahead/behind past empty bot messages (which never render) so
          // grouping reflects the actually-visible bubbles, not raw adjacency.
          const isFollowedByBot = hasRenderedBotInDirection(index, 1);
          const isPrecededByBot = hasRenderedBotInDirection(index, -1);
          // Only the active turn's bubble (the last rendered one) is suppressed
          // while the conversation is busy — finished turns keep their actions.
          const suppressForBusy =
            index === lastRenderedIndex && isConversationBusy;

          if (
            message.type === "bot" &&
            !isBotMessageEmpty(messageProps as ChatBubbleBotProps)
          ) {
            return (
              <ChatBubbleBot
                key={message.message_id || index}
                {...getMessageProps(message, "bot", messagePropsOptions)}
                disableActions={isFollowedByBot || suppressForBusy}
                follow_up_actions={
                  isFollowedByBot || suppressForBusy
                    ? undefined
                    : messageProps.follow_up_actions
                }
                date={isFollowedByBot ? undefined : messageProps.date}
                isGroupedWithNext={isFollowedByBot}
                isGroupedWithPrev={isPrecededByBot}
              />
            );
          }
          return (
            <ChatBubbleUser
              key={message.message_id || index}
              {...messageProps}
            />
          );
        },
      )}
      {(isLoading || isAwaitingExecutorResult) && (
        <AnimatePresence>
          <LoadingIndicator
            loadingText={loadingText}
            loadingTextKey={loadingTextKey}
            toolInfo={toolInfo}
          />
        </AnimatePresence>
      )}
    </>
  );
}
