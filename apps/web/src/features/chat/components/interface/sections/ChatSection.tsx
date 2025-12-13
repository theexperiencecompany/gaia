import type React from "react";

import ChatRenderer from "@/features/chat/components/interface/ChatRenderer";

interface ChatSectionProps {
  chatRef: React.RefObject<HTMLDivElement | null>;
}

export const ChatSection: React.FC<ChatSectionProps> = ({ chatRef }) => {
  return (
    <div
      ref={chatRef}
      className="conversation_history mx-auto w-full max-w-(--breakpoint-lg) p-2 sm:p-4"
    >
      <ChatRenderer />
    </div>
  );
};
