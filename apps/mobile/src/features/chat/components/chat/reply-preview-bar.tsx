import { Pressable, View } from "react-native";
import Animated, { FadeInDown, FadeOutUp } from "react-native-reanimated";
import { AppIcon, Cancel01Icon, LinkBackwardIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { ReplyToMessageData } from "../../types";

interface ReplyPreviewBarProps {
  replyTo: ReplyToMessageData;
  onDismiss: () => void;
}

export function ReplyPreviewBar({ replyTo, onDismiss }: ReplyPreviewBarProps) {
  const { spacing, fontSize, iconSize } = useResponsive();

  const preview =
    replyTo.content.length > 80
      ? `${replyTo.content.slice(0, 80).trim()}...`
      : replyTo.content;

  const label = replyTo.role === "user" ? "You" : "GAIA";

  return (
    <Animated.View
      entering={FadeInDown.duration(200)}
      exiting={FadeOutUp.duration(150)}
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm,
        backgroundColor: "rgba(63,63,70,0.4)",
      }}
    >
      <AppIcon
        icon={LinkBackwardIcon}
        size={iconSize.sm - 2}
        color="#71717a"
        style={{ marginRight: spacing.xs }}
      />

      <View style={{ flex: 1, overflow: "hidden" }}>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#71717a",
            fontWeight: "600",
            marginBottom: 1,
          }}
        >
          Replying to {label}
        </Text>
        <Text
          style={{
            fontSize: fontSize.xs + 1,
            color: "#a1a1aa",
          }}
          numberOfLines={1}
        >
          {preview}
        </Text>
      </View>

      <Pressable
        onPress={onDismiss}
        hitSlop={8}
        style={{ marginLeft: spacing.sm }}
      >
        <AppIcon icon={Cancel01Icon} size={iconSize.sm - 2} color="#71717a" />
      </Pressable>
    </Animated.View>
  );
}
