import { ChatRenderer } from "@chat-ui";
import type React from "react";

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
