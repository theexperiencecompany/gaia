"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { turnManager } from "@/features/chat/stream/turnManager";
import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";
import type { MessageType } from "@/types/features/convoTypes";

export interface UseOnboardingChatReturn {
  streamMessages: IMessage[];
  chatInputValue: string;
  isChatSending: boolean;
  isTodoExecutionDone: boolean;
  setChatInputValue: (value: string) => void;
  sendChatMessage: (content: string) => Promise<void>;
}

export function useOnboardingChat(
  conversationId: string | null,
  pendingTodoMessage?: string | null,
): UseOnboardingChatReturn {
  const [chatInputValue, setChatInputValue] = useState("");
  const [isTodoExecutionDone, setIsTodoExecutionDone] = useState(false);

  // Sending == this conversation has an active turn session.
  const isChatSending = useStreamStore((state) =>
    conversationId ? state.sessions[conversationId] != null : false,
  );
  const activeConversationIdRef = useRef<string | null>(null);
  const sentTodoMessagesRef = useRef<Set<string>>(new Set());
  const todoExecutionInProgressRef = useRef(false);

  const streamMessages = useChatStore(
    useShallow((state) =>
      conversationId
        ? (state.messagesByConversation[conversationId] ?? [])
        : [],
    ),
  );

  useEffect(() => {
    if (!conversationId) return;
    if (activeConversationIdRef.current === conversationId) return;
    useChatStore.getState().setActiveConversationId(conversationId);
    activeConversationIdRef.current = conversationId;
  }, [conversationId]);

  // Latch completion during render instead of adjusting state in effects that
  // react to streaming/message-store changes. Done when either an assistant
  // reply is already persisted (covers remounts) or our initiated execution
  // finished sending. Clearing todoExecutionInProgressRef here would be dead:
  // its only reader below is guarded by !isTodoExecutionDone, and once the
  // latch sets, isTodoExecutionDone never resets.
  const hasSentAssistantReply = streamMessages.some(
    (m) => m.role === "assistant" && m.status === "sent",
  );
  if (
    !isTodoExecutionDone &&
    (hasSentAssistantReply ||
      (todoExecutionInProgressRef.current && !isChatSending))
  ) {
    setIsTodoExecutionDone(true);
  }

  const sendChatMessage = useCallback(
    async (content: string) => {
      const trimmed = content.trim();
      if (!trimmed || !conversationId || isChatSending) return;

      if (activeConversationIdRef.current !== conversationId) {
        useChatStore.getState().setActiveConversationId(conversationId);
        activeConversationIdRef.current = conversationId;
      }

      const userMessageId =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? `onboarding-user-${crypto.randomUUID()}`
          : `onboarding-user-${Date.now()}-${Math.random().toString(36).slice(2)}`;

      setChatInputValue("");

      const userMessage: MessageType = {
        type: "user",
        response: trimmed,
        date: new Date().toISOString(),
        message_id: userMessageId,
      };

      turnManager.send({
        inputText: trimmed,
        userMessage,
        options: {
          fileData: [],
          selectedTool: null,
          toolCategory: null,
          selectedWorkflow: null,
          selectedCalendarEvent: null,
          optimisticUserId: userMessageId,
          replyToMessage: null,
          conversationId,
          isOnboardingDemo: true,
        },
      });
    },
    [conversationId, isChatSending],
  );

  useEffect(() => {
    if (!pendingTodoMessage || !conversationId) return;
    const key = `${conversationId}::${pendingTodoMessage}`;
    if (sentTodoMessagesRef.current.has(key)) return;
    sentTodoMessagesRef.current.add(key);
    todoExecutionInProgressRef.current = true;
    void sendChatMessage(pendingTodoMessage);
  }, [pendingTodoMessage, conversationId, sendChatMessage]);

  return {
    streamMessages,
    chatInputValue,
    isChatSending,
    isTodoExecutionDone,
    setChatInputValue,
    sendChatMessage,
  };
}
