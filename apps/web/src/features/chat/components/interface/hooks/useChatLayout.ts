import { useParams, useRouter } from "next/navigation";
import { useMemo, useRef } from "react";

import { SystemPurpose } from "@/features/chat/api/chatApi";
import { rowShows } from "@/features/chat/components/interface/rows/rows";
import { useChatRows } from "@/features/chat/hooks/useChatRows";
import { useConversationRow } from "@/features/chat/hooks/useConversationList";

interface UseChatLayoutReturn {
  hasMessages: boolean;
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
  const rows = useChatRows();
  const { id: convoIdParam } = useParams<{ id: string }>();
  const conversation = useConversationRow(convoIdParam);

  const chatRef = useRef<HTMLDivElement>(null);
  const dummySectionRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileUploadRef = useRef<{
    attachFiles: (files: File[]) => Promise<void>;
  } | null>(null);

  // The chat layout shows once a row draws something.
  const alwaysShowsGaia =
    conversation?.is_system_generated === true &&
    conversation.system_purpose === SystemPurpose.EMAIL_PROCESSING;
  const hasMessages = useMemo(
    () => rows.some((row) => rowShows(row, alwaysShowsGaia)),
    [rows, alwaysShowsGaia],
  );

  return {
    hasMessages,
    chatRef,
    dummySectionRef,
    inputRef,
    fileUploadRef,
    router,
    convoIdParam,
  };
};
