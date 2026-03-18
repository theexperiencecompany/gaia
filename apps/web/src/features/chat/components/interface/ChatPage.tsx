"use client";

import { useRouter, useSearchParams } from "next/navigation";
import React, { useEffect, useRef, useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { VoiceApp } from "@/features/chat/components/composer/VoiceModeOverlay";
import { FileDropModal } from "@/features/chat/components/files/FileDropModal";
import { useChatLayout } from "@/features/chat/components/interface/hooks/useChatLayout";
import { useScrollBehavior } from "@/features/chat/components/interface/hooks/useScrollBehavior";
import { ChatWithMessages } from "@/features/chat/components/interface/layouts/ChatWithMessages";
import { NewChatLayout } from "@/features/chat/components/interface/layouts/NewChatLayout";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useFetchIntegrationStatus } from "@/features/integrations/hooks/useIntegrations";
import { useDragAndDrop } from "@/hooks/ui/useDragAndDrop";
import { useSendMessage } from "@/hooks/useSendMessage";
import { db } from "@/lib/db/chatDb";
import { syncSingleConversation } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";
import {
  useComposerTextActions,
  usePendingPrompt,
} from "@/stores/composerStore";
import { useWorkflowSelectionStore } from "@/stores/workflowSelectionStore";
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

  // --- Workflow auto-send ---
  // This runs at the ChatPage level (not inside Composer) so that the
  // useChatStream refs survive the NewChatLayout → ChatWithMessages remount.
  const sendMessage = useSendMessage();
  const selectedWorkflow = useWorkflowSelectionStore((s) => s.selectedWorkflow);
  const autoSend = useWorkflowSelectionStore((s) => s.autoSend);
  const autoSendFiredRef = useRef(false);
  const shouldSync = searchParams.get("sync") === "true";
  const queryParam = searchParams.get("q");

  // Fetching status on chat-page to resolve caching issues when new integration is connected
  useFetchIntegrationStatus({
    refetchOnMount: "always",
  });

  // Workflow auto-send: when navigating from /todos with a selected workflow,
  // send "Run this workflow" automatically. This MUST live in ChatPage (not
  // Composer) because Composer remounts when hasMessages toggles from false→true,
  // which orphans the useChatStream refs and kills the streaming connection.
  useEffect(() => {
    if (!(selectedWorkflow && autoSend)) return;
    if (autoSendFiredRef.current) return;
    autoSendFiredRef.current = true;

    const workflow = selectedWorkflow;
    useWorkflowSelectionStore.getState().clearSelectedWorkflow();
    useChatStore.getState().setActiveConversationId(null);

    // Defer to next tick so the store updates (clearSelectedWorkflow,
    // setActiveConversationId) are processed first and useConversation
    // correctly shows the optimistic message.
    setTimeout(() => {
      sendMessage("Run this workflow", {
        selectedWorkflow: workflow,
        selectedTool: null,
        selectedToolCategory: null,
        conversationId: null,
      });
    }, 0);
  }, [selectedWorkflow, autoSend, sendMessage]);

  // Reset the auto-send guard when the workflow/autoSend state clears
  useEffect(() => {
    if (!selectedWorkflow || !autoSend) autoSendFiredRef.current = false;
  }, [selectedWorkflow, autoSend]);

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
    <div className="flex h-full min-h-0 flex-col">
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
