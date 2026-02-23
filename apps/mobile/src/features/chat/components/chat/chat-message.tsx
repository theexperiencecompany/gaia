import { Pressable, View } from "react-native";
import { MessageBubble } from "@/components/ui/message-bubble";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { ToolDataRenderer } from "../../tool-data";
import type { Message } from "../../types";
import { splitMessageByBreaks } from "../../utils/messageBreakUtils";

interface FollowUpActionsProps {
  actions: string[];
  onActionPress?: (action: string) => void;
}

function FollowUpActions({ actions, onActionPress }: FollowUpActionsProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  if (!actions.length) return null;

  return (
    <View
      style={{
        marginTop: spacing.sm,
        flexDirection: "row",
        flexWrap: "wrap",
        gap: spacing.sm,
        paddingLeft: moderateScale(32, 0.5),
      }}
    >
      {actions.map((action) => (
        <Pressable
          key={action}
          onPress={() => onActionPress?.(action)}
          style={{
            borderRadius: moderateScale(8, 0.5),
            borderWidth: 2,
            borderStyle: "dotted",
            borderColor: "rgba(255,255,255,0.1)",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm,
          }}
        >
          <Text style={{ fontSize: fontSize.xs, color: "#ffffff" }}>
            {action}
          </Text>
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
  const { spacing, width } = useResponsive();

  const rawText = message.text ?? "";
  const messageParts = splitMessageByBreaks(rawText).filter(Boolean);

  const hasContent = messageParts.length > 0;
  const showLoadingState = !isUser && isLoading && !hasContent;

  // Message max width adapts to screen size (85% of screen width, min 280, max 400)
  const messageMaxWidth = Math.min(Math.max(width * 0.85, 280), 400);

  return (
    <View
      style={{
        flexDirection: "column",
        paddingVertical: spacing.sm,
        alignItems: isUser ? "flex-end" : "flex-start",
      }}
    >
      <View
        style={{
          flexDirection: "column",
          gap: spacing.sm,
          paddingHorizontal: spacing.md,
          maxWidth: messageMaxWidth,
        }}
      >
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
