import { Surface } from "heroui-native";
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

  const preview = replyToMessage.content;

  const label = replyToMessage.role === "user" ? "You" : "GAIA";

  return (
    <Surface
      style={{
        backgroundColor: "#3f3f46",
        borderRadius: 16,
        paddingHorizontal: spacing.sm,
        paddingVertical: spacing.xs + 2,
        marginBottom: spacing.xs,
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.xs,
        overflow: "hidden",
      }}
    >
      <AppIcon
        icon={LinkBackwardIcon}
        size={iconSize.sm - 4}
        color="#71717a"
        style={{ marginTop: 2 }}
      />

      <View style={{ flex: 1, gap: 1 }}>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#71717a",
            fontWeight: "600",
          }}
        >
          {label}
        </Text>
        <Text
          style={{
            fontSize: fontSize.xs + 1,
            color: isUserMessage ? "rgba(255,255,255,0.7)" : "#a1a1aa",
          }}
          numberOfLines={1}
        >
          {preview}
        </Text>
      </View>
    </Surface>
  );
}
