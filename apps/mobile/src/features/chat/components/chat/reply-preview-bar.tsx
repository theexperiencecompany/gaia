import { Surface } from "heroui-native";
import { Pressable, View } from "react-native";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
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
      entering={FadeIn.duration(200)}
      exiting={FadeOut.duration(150)}
    >
      <Surface
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
          borderTopWidth: 1,
          borderTopColor: "rgba(99,102,241,0.25)",
          backgroundColor: "rgba(99,102,241,0.06)",
        }}
      >
        <AppIcon
          icon={LinkBackwardIcon}
          size={iconSize.sm - 2}
          color="#6366f1"
          style={{ marginRight: spacing.xs }}
        />

        <View style={{ flex: 1, overflow: "hidden" }}>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#6366f1",
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
          <AppIcon icon={Cancel01Icon} size={iconSize.sm - 2} color="#8e8e93" />
        </Pressable>
      </Surface>
    </Animated.View>
  );
}
