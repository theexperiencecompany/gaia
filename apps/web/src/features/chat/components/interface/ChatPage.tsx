"use client";

import { useRouter, useSearchParams } from "next/navigation";
import React, { useEffect, useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { VoiceApp } from "@/features/chat/components/composer/VoiceModeOverlay";
import { FileDropModal } from "@/features/chat/components/files/FileDropModal";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useFetchIntegrationStatus } from "@/features/integrations";
import { useDragAndDrop } from "@/hooks/ui/useDragAndDrop";
import { db } from "@/lib/db/chatDb";
import { syncSingleConversation } from "@/services";
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
  const router = useRouter();
  const searchParams = useSearchParams();
  const shouldSync = searchParams.get("sync") === "true";
  const queryParam = searchParams.get("q");

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

      syncSingleConversation(convoIdParam);
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

  // Handle ?q= query parameter for external app deep linking
  useEffect(() => {
    if (queryParam && appendToInputRef.current) {
      appendToInputRef.current(queryParam);
      const url = new URL(window.location.href);
      url.searchParams.delete("q");
      router.replace(url.pathname + url.search, { scroll: false });
    }
  }, [queryParam, appendToInputRef, router]);

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
