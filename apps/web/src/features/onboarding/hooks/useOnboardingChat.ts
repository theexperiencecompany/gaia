"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useChatStream } from "@/features/chat/hooks/useChatStream";
import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import type { MessageType } from "@/types/features/convoTypes";

export interface UseOnboardingChatReturn {
  streamMessages: IMessage[];
  chatInputValue: string;
  isChatSending: boolean;
  isTodoExecutionDone: boolean;
  setChatInputValue: (value: string) => void;
  sendChatMessage: (content: string) => Promise<void>;
}

/**
 * Bridges the chat stage to the global chat stream + store for the welcome
 * conversation. Subscribes to `messagesByConversation[conversationId]`,
 * exposes input/sending state, and auto-sends `pendingTodoMessage` exactly
 * once per (conversation, message) pair when both are present so a user
 * clicking "Run now" on a todo lands the message into the live chat.
 * Tracks completion of that auto-send via `isTodoExecutionDone` so the page
 * can surface a "Continue to GAIA" CTA.
 */
export function useOnboardingChat(
  conversationId: string | null,
  pendingTodoMessage?: string | null,
): UseOnboardingChatReturn {
  const [chatInputValue, setChatInputValue] = useState("");
  const [isChatSending, setIsChatSending] = useState(false);
  const [isTodoExecutionDone, setIsTodoExecutionDone] = useState(false);

  const fetchChatStream = useChatStream();
  const activeConversationIdRef = useRef<string | null>(null);
  const sentTodoMessagesRef = useRef<Set<string>>(new Set());
  const todoExecutionInProgressRef = useRef(false);

  // Subscribe to full IMessage[] from the store for this conversation
  const streamMessages = useChatStore(
    useShallow((state) =>
      conversationId
        ? (state.messagesByConversation[conversationId] ?? [])
        : [],
    ),
  );

  // Set active conversation so useChatStream posts to the right place.
  // Re-runs if conversationId changes (e.g. after restart).
  useEffect(() => {
    if (!conversationId) return;
    if (activeConversationIdRef.current === conversationId) return;
    useChatStore.getState().setActiveConversationId(conversationId);
    activeConversationIdRef.current = conversationId;
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

      if (activeConversationIdRef.current !== conversationId) {
        useChatStore.getState().setActiveConversationId(conversationId);
        activeConversationIdRef.current = conversationId;
      }

      const userMessageId =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? `onboarding-user-${crypto.randomUUID()}`
          : `onboarding-user-${Date.now()}-${Math.random().toString(36).slice(2)}`;

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

  // Auto-send pending todo message as soon as the conversation is ready.
  // Keyed by message content + conversation so a remount within the same
  // conversation can't double-send, but a new conversation re-arms.
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
