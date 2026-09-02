import { useParams, useRouter } from "next/navigation";
import { useMemo, useRef } from "react";

import { useConversation } from "@/features/chat/hooks/useConversation";
import { useConversationList } from "@/features/chat/hooks/useConversationList";
import { filterEmptyMessagePairs } from "@/features/chat/utils/messageContentUtils";

interface UseChatLayoutReturn {
  hasMessages: boolean;
  isWelcomeConversation: boolean;
  chatRef: React.RefObject<HTMLDivElement | null>;
  dummySectionRef: React.RefObject<HTMLDivElement | null>;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  fileUploadRef: React.RefObject<{
    attachFiles: (files: File[]) => Promise<void>;
  } | null>;
  router: ReturnType<typeof useRouter>;
  convoIdParam: string;
}

export const useChatLayout = (): UseChatLayoutReturn => {
  const router = useRouter();
  const { convoMessages } = useConversation();
  const { conversations } = useConversationList();
  const { id: convoIdParam } = useParams<{ id: string }>();

  const chatRef = useRef<HTMLDivElement>(null);
  const dummySectionRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileUploadRef = useRef<{
    attachFiles: (files: File[]) => Promise<void>;
  } | null>(null);
  // Find the current conversation
  const conversation = useMemo(() => {
    return conversations.find(
      (convo) => convo.conversation_id === convoIdParam,
    );
  }, [conversations, convoIdParam]);

  // Check if there are any messages to determine layout
  const hasMessages = useMemo(() => {
    if (!convoMessages) return false;

    const filteredMessages = filterEmptyMessagePairs(
      convoMessages,
      conversation?.is_system_generated || false,
      conversation?.system_purpose || undefined,
    );

    return filteredMessages.length > 0;
  }, [
    convoMessages,
    conversation?.is_system_generated,
    conversation?.system_purpose,
  ]);

  const isWelcomeConversation =
    conversation?.is_onboarding_conversation === true;

  return {
    hasMessages,
    isWelcomeConversation,
    chatRef,
    dummySectionRef,
    inputRef,
    fileUploadRef,
    router,
    convoIdParam,
  };
};
