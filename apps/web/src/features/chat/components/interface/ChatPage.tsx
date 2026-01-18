"use client";

import { useSearchParams } from "next/navigation";
import React, { useEffect, useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { VoiceApp } from "@/features/chat/components/composer/VoiceModeOverlay";
import { FileDropModal } from "@/features/chat/components/files/FileDropModal";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useFetchIntegrationStatus } from "@/features/integrations";
import { useDragAndDrop } from "@/hooks/ui/useDragAndDrop";
import { db } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import {
  useComposerTextActions,
  usePendingPrompt,
} from "@/stores/composerStore";

import { useChatLayout, useScrollBehavior } from "./hooks";
import { ChatWithMessages, NewChatLayout } from "./layouts";
import ScrollToBottomButton from "./ScrollToBottomButton";

const ChatPage = React.memo(function MainChat() {
  const [voiceModeActive, setVoiceModeActive] = useState(false);
  const { convoMessages } = useConversation();
  const pendingPrompt = usePendingPrompt();
  const { clearPendingPrompt } = useComposerTextActions();
  const setActiveConversationId = useChatStore(
    (state) => state.setActiveConversationId,
  );
  const searchParams = useSearchParams();
  const shouldSync = searchParams.get("sync") === "true";

  // Fetching status on chat-page to resolve caching issues when new integration is connected
  useFetchIntegrationStatus({
    refetchOnMount: "always",
  });

  const {
    hasMessages,
    chatRef,
    dummySectionRef,
    inputRef,
    droppedFiles,
    setDroppedFiles,
    fileUploadRef,
    appendToInputRef,
    convoIdParam,
  } = useChatLayout();

  // Set active conversation ID and mark as read when opening
  useEffect(() => {
    setActiveConversationId(convoIdParam || null);

    // Mark conversation as read if it's unread
    // Using getState() to avoid re-running when conversations update
    if (convoIdParam) {
      const conversations = useChatStore.getState().conversations;
      const conversation = conversations.find((c) => c.id === convoIdParam);
      if (conversation?.isUnread) {
        // Optimistically update local state
        useChatStore
          .getState()
          .upsertConversation({ ...conversation, isUnread: false });
        db.updateConversationFields(convoIdParam, { isUnread: false });
        // Fire API call (don't await to avoid blocking)
        chatApi.markAsRead(convoIdParam).catch(console.error);
      }

      // Sync messages from backend if coming from voice call (sync=true param)
      // This ensures voice messages are fetched without manual IndexedDB persistence
      if (shouldSync) {
        const syncMessagesFromBackend = async () => {
          try {
            const remoteMessages = await chatApi.fetchMessages(convoIdParam);
            if (remoteMessages.length > 0) {
              const mappedMessages = remoteMessages.map((msg, index) => {
                const createdAt = msg.date ? new Date(msg.date) : new Date();
                const role = msg.type === "user" ? "user" : "assistant";
                const messageId =
                  msg.message_id ||
                  `${convoIdParam}-${index}-${createdAt.getTime()}`;

                return {
                  id: messageId,
                  conversationId: convoIdParam,
                  content: msg.response,
                  role: role as "user" | "assistant",
                  status: "sent" as const,
                  createdAt,
                  updatedAt: createdAt,
                  messageId: msg.message_id,
                  fileIds: msg.fileIds,
                  fileData: msg.fileData,
                  toolName: msg.selectedTool ?? null,
                  toolCategory: msg.toolCategory ?? null,
                };
              });

              // Use syncMessages to properly merge with any existing local messages
              await db.syncMessages(convoIdParam, mappedMessages);
            }
          } catch (error) {
            console.error("Failed to sync messages after voice call:", error);
          }
        };

        syncMessagesFromBackend();
      }
    }

    // Clear optimistic message when navigating to a different conversation
    // This prevents stale optimistic message from showing in wrong conversations
    return () => {
      useChatStore.getState().clearOptimisticMessage();
    };
  }, [
    convoIdParam,
    setActiveConversationId,
    shouldSync,
    // NOTE: Not including conversations or upsertConversation in deps
    // to avoid re-triggering when manually toggling read/unread status
  ]);

  const {
    scrollContainerRef,
    scrollToBottom,
    handleScroll,
    shouldShowScrollButton,
  } = useScrollBehavior(hasMessages, convoMessages?.length);

  // Drag and drop functionality
  const { isDragging, dragHandlers } = useDragAndDrop({
    onDrop: (files: File[]) => {
      setDroppedFiles(files);
      if (fileUploadRef.current) {
        fileUploadRef.current.handleDroppedFiles(files);
        fileUploadRef.current.openFileUploadModal();
      }
    },
    multiple: true,
  });

  // Handle pending prompt from global composer
  useEffect(() => {
    if (pendingPrompt && appendToInputRef.current) {
      appendToInputRef.current(pendingPrompt);
      clearPendingPrompt();
    }
  }, [pendingPrompt, clearPendingPrompt, appendToInputRef]);

  // Common composer props
  const composerProps = {
    inputRef,
    scrollToBottom,
    fileUploadRef,
    appendToInputRef,
    droppedFiles,
    onDroppedFilesProcessed: () => setDroppedFiles([]),
    hasMessages,
    conversationId: convoIdParam,
    voiceModeActive: () => setVoiceModeActive(true),
  };

  return (
    <div className="flex h-full flex-col">
      <FileDropModal isDragging={isDragging} />

      {voiceModeActive ? (
        <VoiceApp onEndCall={() => setVoiceModeActive(false)} />
      ) : hasMessages ? (
        <>
          <ChatWithMessages
            scrollContainerRef={scrollContainerRef}
            chatRef={chatRef}
            handleScroll={handleScroll}
            dragHandlers={dragHandlers}
            composerProps={composerProps}
          />
          <ScrollToBottomButton
            onScrollToBottom={scrollToBottom}
            shouldShow={shouldShowScrollButton}
            hasMessages={hasMessages}
          />
        </>
      ) : (
        <>
          <NewChatLayout
            scrollContainerRef={scrollContainerRef}
            dummySectionRef={dummySectionRef}
            handleScroll={handleScroll}
            dragHandlers={dragHandlers}
            composerProps={composerProps}
          />
          <ScrollToBottomButton
            onScrollToBottom={scrollToBottom}
            shouldShow={shouldShowScrollButton}
            hasMessages={hasMessages}
          />
        </>
      )}
    </div>
  );
});

export default ChatPage;
