import { View } from "react-native";
import { MessageBubble } from "@/components/ui/message-bubble";
import type { Message } from "../../types";

interface ChatMessageProps {
  message: Message;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.isUser;

  return (
    <View
      className={`flex-row py-2 px-4 ${isUser ? "justify-end" : "justify-start"}`}
    >
      <MessageBubble
        message={message.text}
        variant={isUser ? "sent" : "received"}
      />
    </View>
  );
}
