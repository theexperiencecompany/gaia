import { Divider, Surface } from "heroui-native";
import { View } from "react-native";
import { AppIcon, LinkBackwardIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { ReplyToMessageData } from "../../types";

interface MessageReplyQuoteProps {
  replyToMessage: ReplyToMessageData;
  isUserMessage: boolean;
}

export function MessageReplyQuote({
  replyToMessage,
  isUserMessage,
}: MessageReplyQuoteProps) {
  const { spacing, fontSize, iconSize } = useResponsive();

  const preview =
    replyToMessage.content.length > 60
      ? `${replyToMessage.content.slice(0, 60).trim()}...`
      : replyToMessage.content;

  const label = replyToMessage.role === "user" ? "You" : "GAIA";

  return (
    <Surface
      style={{
        backgroundColor: isUserMessage
          ? "rgba(0,0,0,0.2)"
          : "rgba(255,255,255,0.06)",
        borderRadius: 8,
        borderTopLeftRadius: 2,
        borderBottomLeftRadius: 2,
        paddingHorizontal: spacing.sm,
        paddingVertical: spacing.xs + 2,
        marginBottom: spacing.xs,
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.xs,
        overflow: "hidden",
      }}
    >
      <Divider
        orientation="vertical"
        thickness={3}
        style={{
          backgroundColor: "#6366f1",
          alignSelf: "stretch",
          marginRight: spacing.xs,
        }}
      />

      <AppIcon
        icon={LinkBackwardIcon}
        size={iconSize.sm - 4}
        color="#6366f1"
        style={{ marginTop: 2 }}
      />

      <View style={{ flex: 1, gap: 1 }}>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#6366f1",
            fontWeight: "600",
          }}
        >
          {label}
        </Text>
        <Text
          style={{
            fontSize: fontSize.xs + 1,
            color: isUserMessage ? "rgba(255,255,255,0.6)" : "#71717a",
          }}
          numberOfLines={2}
        >
          {preview}
        </Text>
      </View>
    </Surface>
  );
}
