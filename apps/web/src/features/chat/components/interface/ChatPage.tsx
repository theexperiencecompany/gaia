"use client";

import React, { useCallback } from "react";
import {
  MessageScrollerProvider,
  useMessageScroller,
} from "@/components/ui/message-scroller";
import Composer from "@/features/chat/components/composer/Composer";
import { PaywallNotice } from "@/features/chat/components/composer/PaywallNotice";

import { FileDropModal } from "@/features/chat/components/files/FileDropModal";
import { FounderLetter } from "@/features/chat/components/interface/founder-letter/FounderLetter";
import { useActiveConversation } from "@/features/chat/components/interface/hooks/useActiveConversation";
import { useAutoSendPendingPrompt } from "@/features/chat/components/interface/hooks/useAutoSendPendingPrompt";
import { useChatLayout } from "@/features/chat/components/interface/hooks/useChatLayout";
import { useVoiceModeControls } from "@/features/chat/components/interface/hooks/useVoiceModeControls";
import { useWorkflowAutoSend } from "@/features/chat/components/interface/hooks/useWorkflowAutoSend";
import { ChatWithMessages } from "@/features/chat/components/interface/layouts/ChatWithMessages";
import { NewChatLayout } from "@/features/chat/components/interface/layouts/NewChatLayout";
import {
  VoiceControlBarContainer,
  VoiceControlBarSlot,
} from "@/features/chat/components/voice-agent/VoiceControlBarContainer";
import { VoiceModeBackground } from "@/features/chat/components/voice-agent/VoiceModeBackground";
import { useStreamResume } from "@/features/chat/hooks/useStreamResume";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useDragAndDrop } from "@/hooks/ui/useDragAndDrop";
import { toast } from "@/lib/toast";

const MainChat = React.memo(function MainChat() {
  // Mounting useIntegrations refreshes the personalized catalog (staleTime: 0)
  // so the composer's tool lock state is current when a chat opens.
  useIntegrations();
  useWorkflowAutoSend();

  const {
    hasMessages,
    isWelcomeConversation,
    chatRef,
    dummySectionRef,
    inputRef,
    fileUploadRef,
    convoIdParam,
  } = useChatLayout();

  // Reload-mid-stream recovery: if this conversation has a turn still running
  // server-side, re-attach to its event log and keep streaming live. Also owns
  // the on-open freshness sync, sequenced AFTER resume — syncing first would
  // race the live-turn discovery and sweep the optimistic user message.
  useStreamResume(convoIdParam || null);
  useActiveConversation(convoIdParam);

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
      if (!fileUploadRef.current) {
        toast.error("File upload isn't available during a voice call");
        return;
      }
      fileUploadRef.current.attachFiles(files);
    },
    multiple: true,
  });

  useAutoSendPendingPrompt();

  const { voiceModeActive, onVoiceModeHover, startVoiceMode, endVoiceCall } =
    useVoiceModeControls(convoIdParam);

  const composerProps = {
    inputRef,
    scrollToBottom,
    fileUploadRef,
    hasMessages,
    onVoiceModeHover,
    voiceModeActive: startVoiceMode,
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
        <VoiceControlBarContainer>
          <VoiceModeBackground />
          <ChatWithMessages
            chatRef={chatRef}
            dragHandlers={dragHandlers}
            bottomBar={<VoiceControlBarSlot onEndCall={endVoiceCall} />}
          />
        </VoiceControlBarContainer>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <FileDropModal isDragging={isDragging} />
      {/* The founder's letter — bottom-right of every chat, hidden during voice calls. */}
      <FounderLetter hidden={voiceModeActive} />

      {useMessagesLayout ? (
        <ChatWithMessages
          chatRef={chatRef}
          dragHandlers={dragHandlers}
          bottomBar={
            <>
              <PaywallNotice className="mb-10" />
              <Composer {...composerProps} />
            </>
          }
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
