"use client";

import { AnimatePresence } from "framer-motion";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import CreatedByGAIABanner from "@/features/chat/components/banners/CreatedByGAIABanner";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import SearchedImageDialog from "@/features/chat/components/bubbles/bot/SearchedImageDialog";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import GeneratedImageSheet from "@/features/chat/components/image/GeneratedImageSheet";
import { LoadingIndicator } from "@/features/chat/components/interface/LoadingIndicator";
import MemoryModal from "@/features/chat/components/memory/MemoryModal";
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
  const searchParams = useSearchParams();
  const messageId = searchParams.get("messageId");
  const { isLoading } = useLoading();
  const { loadingText, loadingTextKey, toolInfo } = useLoadingText();
  const { id: urlConvoId } = useParams<{ id: string }>();
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  // Use URL param first, fallback to store's activeConversationId (for new chats before URL updates)
  const convoIdParam = urlConvoId || activeConversationId;
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

  // Handle retry callback
  const handleRetry = useCallback(
    (msgId: string) => {
      console.log("[ChatRenderer] handleRetry called:", {
        convoIdParam,
        msgId,
      });
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
    if (
      messageId &&
      messagesWithDeduplicatedToolCalls.length > 0 &&
      scrolledToMessageRef.current !== messageId
    ) {
      scrollToMessage(messageId);
      scrolledToMessageRef.current = messageId;
    }
  }, [messageId, messagesWithDeduplicatedToolCalls]);

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
      <title id="chat_title">
        {`${
          conversations.find((convo) => convo.conversation_id === convoIdParam)
            ?.description || "New chat"
        } | GAIA`}
      </title>
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
      {messagesWithDeduplicatedToolCalls?.map(
        (message: MessageType, index: number) => {
          let messageProps = null;

          if (message.type === "bot")
            messageProps = getMessageProps(message, "bot", messagePropsOptions);
          else if (message.type === "user")
            messageProps = getMessageProps(
              message,
              "user",
              messagePropsOptions,
            );

          if (!messageProps) return null;

          if (
            message.type === "bot" &&
            !isBotMessageEmpty(messageProps as ChatBubbleBotProps)
          )
            return (
              <ChatBubbleBot
                key={message.message_id || index}
                {...getMessageProps(message, "bot", messagePropsOptions)}
              />
            );

          return (
            <ChatBubbleUser
              key={message.message_id || index}
              {...messageProps}
            />
          );
        },
      )}
      {isLoading && (
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
