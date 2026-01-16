import { Pressable, View } from "react-native";
import { MessageBubble } from "@/components/ui/message-bubble";
import { Text } from "@/components/ui/text";
import { ToolDataRenderer } from "../../tool-data";
import type { Message } from "../../types";
import { splitMessageByBreaks } from "../../utils/messageBreakUtils";

interface FollowUpActionsProps {
  actions: string[];
  onActionPress?: (action: string) => void;
}

function FollowUpActions({ actions, onActionPress }: FollowUpActionsProps) {
  if (!actions.length) return null;

  return (
    <View className="mt-2 flex-row flex-wrap gap-2 pl-8">
      {actions.map((action) => (
        <Pressable
          key={action}
          onPress={() => onActionPress?.(action)}
          className="rounded-lg border-2 border-dotted border-muted/20 px-3 py-2 active:opacity-70"
        >
          <Text className="text-xs text-foreground">{action}</Text>
        </Pressable>
      ))}
    </View>
  );
}

interface ChatMessageProps {
  message: Message;
  onFollowUpAction?: (action: string) => void;
  isLoading?: boolean;
  loadingMessage?: string;
}

export function ChatMessage({
  message,
  onFollowUpAction,
  isLoading = false,
  loadingMessage = "Thinking...",
}: ChatMessageProps) {
  const isUser = message.isUser;

  const rawText = message.text ?? "";
  const messageParts = splitMessageByBreaks(rawText).filter(Boolean);

  const hasContent = messageParts.length > 0;
  const showLoadingState = !isUser && isLoading && !hasContent;

  return (
    <View className={`flex-col py-2 ${isUser ? "items-end" : "items-start"}`}>
      <View className="flex-col gap-2 px-4" style={{ maxWidth: "85%" }}>
        {!isUser && message.toolData?.length ? (
          <ToolDataRenderer toolData={message.toolData} />
        ) : null}

        {showLoadingState ? (
          <MessageBubble message={loadingMessage} variant="loading" />
        ) : (
          messageParts.map((part, index) => (
            <MessageBubble
              key={`${message.id}-${index}`}
              message={part}
              variant={isUser ? "sent" : "received"}
              showAvatar={!isUser && index === 0}
              grouped={
                messageParts.length === 1
                  ? "none"
                  : index === 0
                    ? "first"
                    : index === messageParts.length - 1
                      ? "last"
                      : "middle"
              }
            />
          ))
        )}
      </View>

      {!isUser && message.followUpActions?.length ? (
        <FollowUpActions
          actions={message.followUpActions}
          onActionPress={onFollowUpAction}
        />
      ) : null}
    </View>
  );
}
