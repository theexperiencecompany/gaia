import {
  getRandomThinkingMessage,
  getRelevantThinkingMessage,
} from "@gaia/shared/utils";
import { PressableFeedback } from "heroui-native";
import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { AppIcon, ArrowDown02Icon, Brain02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { colors } from "@/lib/design-tokens";
import { useResponsive } from "@/lib/responsive";
import { Pulsing } from "../streaming/pulsing";

interface ThinkingBubbleProps {
  thinkingContent: string;
  isStreaming?: boolean;
  userMessage?: string;
  durationSeconds?: number;
}

function ThinkingIndicator({ userMessage }: { userMessage?: string }) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const [message, setMessage] = useState(() =>
    userMessage
      ? getRelevantThinkingMessage(userMessage)
      : getRandomThinkingMessage(),
  );

  useEffect(() => {
    const interval = setInterval(
      () => {
        setMessage(
          userMessage
            ? getRelevantThinkingMessage(userMessage)
            : getRandomThinkingMessage(),
        );
      },
      2000 + Math.random() * 1000,
    );
    return () => clearInterval(interval);
  }, [userMessage]);

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.sm,
      }}
    >
      <Pulsing>
        <AppIcon
          icon={Brain02Icon}
          size={moderateScale(16, 0.5)}
          color={colors.zinc400}
        />
      </Pulsing>
      <Text
        style={{
          fontSize: fontSize.sm,
          color: colors.zinc400,
          fontWeight: "500",
        }}
      >
        {message}...
      </Text>
    </View>
  );
}

export function ThinkingBubble({
  thinkingContent,
  isStreaming = false,
  userMessage,
  durationSeconds,
}: ThinkingBubbleProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const chevronRotation = useSharedValue(0);
  const { spacing, fontSize, moderateScale } = useResponsive();

  const toggleExpanded = useCallback(() => {
    const next = !isExpanded;
    setIsExpanded(next);
    chevronRotation.value = withTiming(next ? 1 : 0, { duration: 250 });
  }, [chevronRotation, isExpanded]);

  const chevronStyle = useAnimatedStyle(() => ({
    transform: [
      {
        rotate: `${chevronRotation.value * 180}deg`,
      },
    ],
  }));

  if (!thinkingContent && !isStreaming) return null;

  // While streaming and no content yet, show the animated indicator
  if (isStreaming && !thinkingContent) {
    return (
      <View style={{ marginBottom: spacing.sm }}>
        <ThinkingIndicator userMessage={userMessage} />
      </View>
    );
  }

  const collapsedLabel =
    !isStreaming && durationSeconds != null
      ? `Reasoned for ${durationSeconds}s`
      : "Thinking...";

  return (
    <View
      style={{
        marginBottom: spacing.sm,
        gap: spacing.sm,
      }}
    >
      <PressableFeedback
        onPress={toggleExpanded}
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          paddingVertical: spacing.xs + 2,
          paddingHorizontal: spacing.xs,
        }}
      >
        <AppIcon
          icon={Brain02Icon}
          size={moderateScale(16, 0.5)}
          color="#a1a1aa"
        />
        <Text
          style={{
            fontSize: fontSize.sm,
            color: "#a1a1aa",
            fontWeight: "500",
            flex: 1,
          }}
        >
          {isExpanded ? "Hide thinking" : collapsedLabel}
        </Text>
        <Animated.View style={chevronStyle}>
          <AppIcon
            icon={ArrowDown02Icon}
            size={moderateScale(14, 0.5)}
            color="#71717a"
          />
        </Animated.View>
      </PressableFeedback>

      {isExpanded ? (
        <View
          style={{
            backgroundColor: "#27272a",
            borderRadius: moderateScale(10, 0.5),
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm + 2,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#a1a1aa",
              lineHeight: 20,
            }}
          >
            {thinkingContent}
          </Text>
        </View>
      ) : null}
    </View>
  );
}
