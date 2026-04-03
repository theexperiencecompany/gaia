"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { useChatStream } from "@/features/chat/hooks/useChatStream";
import { useChatStore } from "@/stores/chatStore";
import type { MessageType } from "@/types/features/convoTypes";

interface OnboardingChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
}

interface UseOnboardingChatReturn {
  chatMessages: OnboardingChatMessage[];
  chatInputValue: string;
  isChatSending: boolean;
  setChatInputValue: (value: string) => void;
  sendChatMessage: (content: string) => Promise<void>;
}

export function useOnboardingChat(
  conversationId: string | null,
): UseOnboardingChatReturn {
  const [chatMessages, setChatMessages] = useState<OnboardingChatMessage[]>([]);
  const [chatInputValue, setChatInputValue] = useState("");
  const [isChatSending, setIsChatSending] = useState(false);
  const fetchChatStream = useChatStream();
  const activeConversationSetRef = useRef(false);
  const pendingBotIdRef = useRef<string | null>(null);

  // Subscribe to store updates to reflect streaming bot messages
  useEffect(() => {
    if (!conversationId) return;

    const unsubscribe = useChatStore.subscribe((state) => {
      const botMessageId = pendingBotIdRef.current;
      if (!botMessageId) return;

      const messages = state.messagesByConversation[conversationId] ?? [];
      // Find the most recent assistant message (backend assigns real ID, different from optimistic)
      const latestBot = [...messages]
        .reverse()
        .find((m) => m.role === "assistant");

      if (latestBot?.content) {
        setChatMessages((prev) =>
          prev.map((m) =>
            m.id === botMessageId
              ? {
                  ...m,
                  content: latestBot.content,
                  isStreaming: latestBot.status === "sending",
                }
              : m,
          ),
        );

        // Clear ref when streaming finishes
        if (latestBot.status === "sent") {
          pendingBotIdRef.current = null;
        }
      }
    });

    return unsubscribe;
  }, [conversationId]);

  // Auto-fetch the seeded first message from the conversation
  const firstMessageFetchedRef = useRef(false);
  useEffect(() => {
    if (!conversationId || firstMessageFetchedRef.current) return;
    firstMessageFetchedRef.current = true;

    // Set active conversation so useChatStream posts to the right place
    useChatStore.getState().setActiveConversationId(conversationId);
    activeConversationSetRef.current = true;

    const fetchFirstMessage = async () => {
      try {
        const messages = await chatApi.fetchMessages(conversationId);
        const firstBotMessage = messages.find(
          (m) => m.type === "bot" && m.response,
        );
        if (firstBotMessage?.response) {
          setChatMessages((prev) => {
            if (prev.length > 0) return prev;
            return [
              {
                id: firstBotMessage.message_id || `seeded-${Date.now()}`,
                role: "assistant" as const,
                content: firstBotMessage.response,
              },
            ];
          });
        }
      } catch {
        // Non-blocking
      }
    };

    void fetchFirstMessage();
  }, [conversationId]);

  const sendChatMessage = useCallback(
    async (content: string) => {
      const trimmed = content.trim();
      if (!trimmed || !conversationId || isChatSending) return;

      // Set active conversation ID so useChatStream posts to the right conversation
      if (!activeConversationSetRef.current) {
        useChatStore.getState().setActiveConversationId(conversationId);
        activeConversationSetRef.current = true;
      }

      const userMessageId = `onboarding-user-${Date.now()}`;
      const botMessageId = `onboarding-bot-${Date.now()}`;

      pendingBotIdRef.current = botMessageId;

      setChatMessages((prev) => [
        ...prev,
        { id: userMessageId, role: "user", content: trimmed },
        { id: botMessageId, role: "assistant", content: "", isStreaming: true },
      ]);
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
        setChatMessages((prev) =>
          prev.map((m) =>
            m.id === botMessageId
              ? {
                  ...m,
                  content: "Sorry, something went wrong. Please try again.",
                  isStreaming: false,
                }
              : m,
          ),
        );
        pendingBotIdRef.current = null;
      } finally {
        setIsChatSending(false);
      }
    },
    [conversationId, isChatSending, fetchChatStream],
  );

  return {
    chatMessages,
    chatInputValue,
    isChatSending,
    setChatInputValue,
    sendChatMessage,
  };
}
