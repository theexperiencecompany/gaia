import type React from "react";

import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";
import { useOlderHistory } from "@/features/chat/hooks/useOlderHistory";

interface ChatSectionProps {
  chatRef: React.RefObject<HTMLDivElement | null>;
}

export const ChatSection: React.FC<ChatSectionProps> = ({ chatRef }) => {
  useOlderHistory();
  return (
    <div
      ref={chatRef}
      className="conversation_history mx-auto w-full max-w-(--breakpoint-lg) p-2 sm:p-4"
    >
      <ChatRenderer />
    </div>
  );
};
