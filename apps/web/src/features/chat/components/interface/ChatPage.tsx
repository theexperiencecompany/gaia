"use client";

import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useRef } from "react";
import {
  MessageScrollerProvider,
  useMessageScroller,
} from "@/components/ui/message-scroller";
import { chatApi } from "@/features/chat/api/chatApi";
import Composer from "@/features/chat/components/composer/Composer";

import { FileDropModal } from "@/features/chat/components/files/FileDropModal";
import { useChatLayout } from "@/features/chat/components/interface/hooks/useChatLayout";
import { ChatWithMessages } from "@/features/chat/components/interface/layouts/ChatWithMessages";
import { NewChatLayout } from "@/features/chat/components/interface/layouts/NewChatLayout";
import { usePrefetchConnectionDetails } from "@/features/chat/components/voice-agent/hooks/useConnectionDetails";
import {
  VoiceControlBarContainer,
  VoiceControlBarSlot,
} from "@/features/chat/components/voice-agent/VoiceControlBarContainer";
import { VoiceModeBackground } from "@/features/chat/components/voice-agent/VoiceModeBackground";
import { useStreamResume } from "@/features/chat/hooks/useStreamResume";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
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
import { usePricingModalStore } from "@/stores/pricingModalStore";
import {
  useDiscoveredConversationId,
  useVoiceModeActions,
  useVoiceModeActive,
} from "@/stores/voiceModeStore";
import { useWorkflowSelectionStore } from "@/stores/workflowSelectionStore";

const MainChat = React.memo(function MainChat() {
  const voiceModeActive = useVoiceModeActive();
  const storeDiscoveredId = useDiscoveredConversationId();
  const { enterVoiceMode, exitVoiceMode } = useVoiceModeActions();
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const openPricingModal = usePricingModalStore((s) => s.openModal);
  const pendingPrompt = usePendingPrompt();
  const { clearPendingPrompt } = useComposerTextActions();
  const setActiveConversationId = useChatStore(
    (state) => state.setActiveConversationId,
  );
  const router = useRouter();

  // --- Workflow auto-send ---
  // Hosted at ChatPage (not Composer) because ChatPage is memoized and never
  // remounts, whereas Composer remounts across the NewChatLayout →
  // ChatWithMessages layout switch that fires when the optimistic message
  // flips hasMessages to true. Keeping the once-only guard (autoSendFiredRef)
  // here stops that remount from resetting it and firing the workflow twice.
  const sendMessage = useSendMessage();
  const selectedWorkflow = useWorkflowSelectionStore((s) => s.selectedWorkflow);
  const autoSend = useWorkflowSelectionStore((s) => s.autoSend);
  const autoSendFiredRef = useRef(false);

  // Mounting useIntegrations refreshes the personalized catalog (staleTime: 0)
  // so the composer's tool lock state is current when a chat opens.
  useIntegrations();

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

  // Reload-mid-stream recovery: if this conversation has a turn still running
  // server-side, re-attach to its event log and keep streaming live.
  useStreamResume(convoIdParam || null);

  // Set active conversation ID and mark as read when opening.
  // During a new voice session (no URL param), use the store's provisional
  // UUID so the chat store points at the correct in-flight conversation —
  // prevents this parent effect from overwriting VoiceSessionInner's ID with null.
  useEffect(() => {
    if (voiceModeActive && !convoIdParam && storeDiscoveredId) {
      setActiveConversationId(storeDiscoveredId);
    } else {
      setActiveConversationId(convoIdParam || null);
    }

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
    voiceModeActive,
    storeDiscoveredId,
    // NOTE: Not including conversations or upsertConversation in deps
    // to avoid re-triggering when manually toggling read/unread status
  ]);

  // Imperative scroll control from the message scroller (Provider wraps this
  // component). Used by the composer to snap to the live edge on send.
  // Instant, not smooth: bubbles use content-visibility:auto, so a smooth
  // scroll lands short as offscreen bubbles resolve their real heights — the
  // instant jump plus autoScroll stickiness pins the view reliably.
  const { scrollToEnd } = useMessageScroller();
  const scrollToBottom = useCallback(() => {
    scrollToEnd();
  }, [scrollToEnd]);

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

  const prefetchConnectionDetails = usePrefetchConnectionDetails(
    convoIdParam || undefined,
  );

  const composerProps = {
    inputRef,
    scrollToBottom,
    fileUploadRef,
    appendToInputRef,
    droppedFiles,
    onDroppedFilesProcessed: () => setDroppedFiles([]),
    hasMessages,
    conversationId: convoIdParam,
    // Warm the session token on hover so clicking starts ~instantly. Gated
    // on subscription — /token is plan-limited and free users get the modal.
    onVoiceModeHover: () => {
      if (subscriptionStatus?.is_subscribed) prefetchConnectionDetails();
    },
    voiceModeActive: () => {
      // Voice mode is paid-only (the /token endpoint enforces it server-side
      // too). Free users get the upgrade modal instead of a session.
      if (!subscriptionStatus?.is_subscribed) {
        trackEvent(ANALYTICS_EVENTS.CHAT_VOICE_MODE_TOGGLED, {
          voice_mode_enabled: false,
          conversation_id: convoIdParam,
          blocked_reason: "upgrade_required",
        });
        openPricingModal();
        return;
      }
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
    // Capture the active id BEFORE exiting (exitVoiceMode clears the store id).
    const activeId = useChatStore.getState().activeConversationId;
    exitVoiceMode();
    if (activeId) {
      // During voice the URL was updated in-place via history.replaceState, so
      // the App Router segment is still /c (convoIdParam undefined for a new
      // chat). A real navigation resolves the conversation route so the
      // just-finished voice chat renders without a manual reload.
      if (!convoIdParam) {
        router.replace(`/c/${activeId}`);
      }
      // Pull server canonical messages so the chat shows them without the
      // in-memory voice turns; prevents duplicate-after-refresh.
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
            chatRef={chatRef}
            dragHandlers={dragHandlers}
            bottomBar={<VoiceControlBarSlot onEndCall={handleEndVoiceCall} />}
          />
        </VoiceControlBarContainer>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <FileDropModal isDragging={isDragging} />

      {useMessagesLayout ? (
        <ChatWithMessages
          chatRef={chatRef}
          dragHandlers={dragHandlers}
          bottomBar={<Composer {...composerProps} />}
        />
      ) : (
        <NewChatLayout
          dummySectionRef={dummySectionRef}
          dragHandlers={dragHandlers}
          composerProps={composerProps}
        />
      )}
    </div>
  );
});

// The provider owns transcript scroll state (stick-to-bottom, scroll button,
// imperative scrollToEnd) for everything below — including the composer slot.
const ChatPage = React.memo(function ChatPage() {
  return (
    <MessageScrollerProvider autoScroll defaultScrollPosition="end">
      <MainChat />
    </MessageScrollerProvider>
  );
});

export default ChatPage;
