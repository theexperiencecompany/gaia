"use client";

import { useRouter } from "next/navigation";
import React, { useEffect, useRef } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import Composer from "@/features/chat/components/composer/Composer";

import { FileDropModal } from "@/features/chat/components/files/FileDropModal";
import { useChatLayout } from "@/features/chat/components/interface/hooks/useChatLayout";
import { useScrollBehavior } from "@/features/chat/components/interface/hooks/useScrollBehavior";
import { ChatWithMessages } from "@/features/chat/components/interface/layouts/ChatWithMessages";
import { NewChatLayout } from "@/features/chat/components/interface/layouts/NewChatLayout";
import {
  VoiceControlBarContainer,
  VoiceControlBarSlot,
} from "@/features/chat/components/voice-agent/VoiceControlBarContainer";
import { VoiceModeBackground } from "@/features/chat/components/voice-agent/VoiceModeBackground";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useFetchIntegrationStatus } from "@/features/integrations/hooks/useIntegrations";
import { useDragAndDrop } from "@/hooks/ui/useDragAndDrop";
import { useSendMessage } from "@/hooks/useSendMessage";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { db } from "@/lib/db/chatDb";
import { syncSingleConversation } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";
import {
  useComposerTextActions,
  usePendingPrompt,
} from "@/stores/composerStore";
import {
  useVoiceModeActions,
  useVoiceModeActive,
} from "@/stores/voiceModeStore";
import { useWorkflowSelectionStore } from "@/stores/workflowSelectionStore";
import ScrollToBottomButton from "./ScrollToBottomButton";

const ChatPage = React.memo(function MainChat() {
  const voiceModeActive = useVoiceModeActive();
  const { enterVoiceMode, exitVoiceMode } = useVoiceModeActions();
  const { convoMessages } = useConversation();
  const pendingPrompt = usePendingPrompt();
  const { clearPendingPrompt } = useComposerTextActions();
  const setActiveConversationId = useChatStore(
    (state) => state.setActiveConversationId,
  );
  const router = useRouter();

  // --- Workflow auto-send ---
  // This runs at the ChatPage level (not inside Composer) so that the
  // useChatStream refs survive the NewChatLayout → ChatWithMessages remount.
  const sendMessage = useSendMessage();
  const selectedWorkflow = useWorkflowSelectionStore((s) => s.selectedWorkflow);
  const autoSend = useWorkflowSelectionStore((s) => s.autoSend);
  const autoSendFiredRef = useRef(false);

  useFetchIntegrationStatus({
    refetchOnMount: "always",
  });

  useEffect(() => {
    if (!(selectedWorkflow && autoSend)) return;
    if (autoSendFiredRef.current) return;
    autoSendFiredRef.current = true;

    const workflow = selectedWorkflow;
    useWorkflowSelectionStore.getState().clearSelectedWorkflow();
    useChatStore.getState().setActiveConversationId(null);

    setTimeout(() => {
      sendMessage("Run this workflow", {
        selectedWorkflow: workflow,
        selectedTool: null,
        selectedToolCategory: null,
        conversationId: null,
      });
    }, 0);
  }, [selectedWorkflow, autoSend, sendMessage]);

  useEffect(() => {
    if (!selectedWorkflow || !autoSend) autoSendFiredRef.current = false;
  }, [selectedWorkflow, autoSend]);

  const {
    hasMessages,
    isWelcomeConversation,
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

    if (convoIdParam) {
      const conversations = useChatStore.getState().conversations;
      const conversation = conversations.find((c) => c.id === convoIdParam);
      if (conversation?.isUnread) {
        useChatStore
          .getState()
          .upsertConversation({ ...conversation, isUnread: false });
        db.updateConversationFields(convoIdParam, { isUnread: false });
        chatApi.markAsRead(convoIdParam).catch(console.error);
      }

      syncSingleConversation(convoIdParam);
    }

    return () => {
      useChatStore.getState().clearOptimisticMessage();
    };
  }, [
    convoIdParam,
    setActiveConversationId,
    // NOTE: Not including conversations or upsertConversation in deps
    // to avoid re-triggering when manually toggling read/unread status
  ]);

  const {
    scrollContainerRef,
    scrollToBottom,
    handleScroll,
    shouldShowScrollButton,
  } = useScrollBehavior(hasMessages, convoMessages?.length);

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

  useEffect(() => {
    if (pendingPrompt && appendToInputRef.current) {
      appendToInputRef.current(pendingPrompt);
      clearPendingPrompt();
    }
  }, [pendingPrompt, clearPendingPrompt, appendToInputRef]);

  useEffect(() => {
    const queryParam = new URLSearchParams(window.location.search).get("q");
    if (queryParam && appendToInputRef.current) {
      appendToInputRef.current(queryParam);
      const url = new URL(window.location.href);
      url.searchParams.delete("q");
      router.replace(url.pathname + url.search, { scroll: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const composerProps = {
    inputRef,
    scrollToBottom,
    fileUploadRef,
    appendToInputRef,
    droppedFiles,
    onDroppedFilesProcessed: () => setDroppedFiles([]),
    hasMessages,
    conversationId: convoIdParam,
    voiceModeActive: () => {
      trackEvent(ANALYTICS_EVENTS.CHAT_VOICE_MODE_TOGGLED, {
        voice_mode_enabled: true,
        conversation_id: convoIdParam,
      });
      enterVoiceMode(convoIdParam || undefined);
    },
  };

  const handleEndVoiceCall = () => {
    trackEvent(ANALYTICS_EVENTS.CHAT_VOICE_MODE_TOGGLED, {
      voice_mode_enabled: false,
      conversation_id: convoIdParam,
    });
    exitVoiceMode();
    // Pull server canonical messages so the chat shows them without the
    // in-memory voice turns; prevents duplicate-after-refresh.
    const activeId = useChatStore.getState().activeConversationId;
    if (activeId) {
      syncSingleConversation(activeId).catch((err) =>
        console.error("[ChatPage] post-voice sync failed", err),
      );
    }
  };

  // Voice mode forces the messages layout so the gradient + bar always have
  // a stable container; the user can speak from a fresh /c without flipping
  // layouts mid-call.
  const useMessagesLayout =
    voiceModeActive || hasMessages || isWelcomeConversation;

  if (voiceModeActive) {
    return (
      // `isolate` creates a new stacking context so the gradient (z-index: -10)
      // paints behind the layout content but ABOVE the ancestor `<main>`'s
      // solid bg-zinc background. Without this, the parent's background covers
      // the gradient entirely (gradient paints in the ancestor's stacking
      // context, below the parent's block-level background).
      <div className="relative isolate flex h-full min-h-0 flex-col">
        <FileDropModal isDragging={isDragging} />
        <VoiceControlBarContainer>
          <VoiceModeBackground />
          <ChatWithMessages
            scrollContainerRef={scrollContainerRef}
            chatRef={chatRef}
            handleScroll={handleScroll}
            dragHandlers={dragHandlers}
            bottomBar={<VoiceControlBarSlot onEndCall={handleEndVoiceCall} />}
          />
        </VoiceControlBarContainer>
        <ScrollToBottomButton
          onScrollToBottom={scrollToBottom}
          shouldShow={shouldShowScrollButton}
          hasMessages={hasMessages}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <FileDropModal isDragging={isDragging} />

      {useMessagesLayout ? (
        <>
          <ChatWithMessages
            scrollContainerRef={scrollContainerRef}
            chatRef={chatRef}
            handleScroll={handleScroll}
            dragHandlers={dragHandlers}
            bottomBar={<Composer {...composerProps} />}
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
