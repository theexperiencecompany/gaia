"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useChatStream } from "@/features/chat/hooks/useChatStream";
import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import type { MessageType } from "@/types/features/convoTypes";

interface UseOnboardingChatReturn {
  streamMessages: IMessage[];
  chatInputValue: string;
  isChatSending: boolean;
  isTodoExecutionDone: boolean;
  isPendingTodoSend: boolean;
  setChatInputValue: (value: string) => void;
  sendChatMessage: (content: string) => Promise<void>;
}

export function useOnboardingChat(
  conversationId: string | null,
  pendingTodoMessage?: string | null,
): UseOnboardingChatReturn {
  const [chatInputValue, setChatInputValue] = useState("");
  const [isChatSending, setIsChatSending] = useState(false);
  const [isTodoExecutionDone, setIsTodoExecutionDone] = useState(false);
  const [isPendingTodoSend, setIsPendingTodoSend] = useState(false);

  const fetchChatStream = useChatStream();
  const activeConversationSetRef = useRef(false);
  const todoSentRef = useRef(false);
  const todoExecutionInProgressRef = useRef(false);

  // Subscribe to full IMessage[] from the store for this conversation
  const streamMessages = useChatStore(
    useShallow((state) =>
      conversationId
        ? (state.messagesByConversation[conversationId] ?? [])
        : [],
    ),
  );

  // Set active conversation so useChatStream posts to the right place
  useEffect(() => {
    if (!conversationId || activeConversationSetRef.current) return;
    useChatStore.getState().setActiveConversationId(conversationId);
    activeConversationSetRef.current = true;
  }, [conversationId]);

  // Detect todo execution completion: isChatSending went true → false while todo was in progress
  useEffect(() => {
    if (!todoExecutionInProgressRef.current) return;
    if (!isChatSending) {
      todoExecutionInProgressRef.current = false;
      setIsTodoExecutionDone(true);
    }
  }, [isChatSending]);

  const sendChatMessage = useCallback(
    async (content: string) => {
      const trimmed = content.trim();
      if (!trimmed || !conversationId || isChatSending) return;

      if (!activeConversationSetRef.current) {
        useChatStore.getState().setActiveConversationId(conversationId);
        activeConversationSetRef.current = true;
      }

      const userMessageId = `onboarding-user-${Date.now()}`;

      setChatInputValue("");
      setIsChatSending(true);

      const userMessage: MessageType = {
        type: "user",
        response: trimmed,
        date: new Date().toISOString(),
        message_id: userMessageId,
      };

      try {
        await fetchChatStream(
          trimmed,
          [userMessage],
          [],
          null,
          null,
          null,
          null,
          userMessageId,
          null,
        );
      } catch {
        // useChatStream handles error toasts internally
      } finally {
        setIsChatSending(false);
      }
    },
    [conversationId, isChatSending, fetchChatStream],
  );

  // Auto-send pending todo message when entering chat from todo execution
  useEffect(() => {
    if (!pendingTodoMessage || !conversationId || todoSentRef.current) return;
    todoSentRef.current = true;
    todoExecutionInProgressRef.current = true;
    setIsPendingTodoSend(true);
    const timer = setTimeout(() => {
      setIsPendingTodoSend(false);
      void sendChatMessage(pendingTodoMessage);
    }, 800);
    return () => clearTimeout(timer);
  }, [pendingTodoMessage, conversationId, sendChatMessage]);

  return {
    streamMessages,
    chatInputValue,
    isChatSending,
    isTodoExecutionDone,
    isPendingTodoSend,
    setChatInputValue,
    sendChatMessage,
  };
}
