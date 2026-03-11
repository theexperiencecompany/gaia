import {
  getRandomThinkingMessage,
  getRelevantThinkingMessage,
} from "@gaia/shared/utils";
import { PressableFeedback, Surface } from "heroui-native";
import { useCallback, useEffect, useRef, useState } from "react";
import { Animated, LayoutAnimation, View } from "react-native";
import { AppIcon, ArrowDown02Icon, Brain02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface ThinkingBubbleProps {
  thinkingContent: string;
  isStreaming?: boolean;
  userMessage?: string;
  durationSeconds?: number;
}

function PulsingBrain({ size }: { size: number }) {
  const opacity = useRef(new Animated.Value(0.5)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 1,
          duration: 600,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.5,
          duration: 600,
          useNativeDriver: true,
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [opacity]);

  return (
    <Animated.View style={{ opacity }}>
      <AppIcon icon={Brain02Icon} size={size} color="#a78bfa" />
    </Animated.View>
  );
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
      <PulsingBrain size={moderateScale(16, 0.5)} />
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#a78bfa",
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
  const chevronRotation = useRef(new Animated.Value(0)).current;
  const { spacing, fontSize, moderateScale } = useResponsive();

  const toggleExpanded = useCallback(() => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setIsExpanded((prev) => {
      const next = !prev;
      Animated.timing(chevronRotation, {
        toValue: next ? 1 : 0,
        duration: 200,
        useNativeDriver: true,
      }).start();
      return next;
    });
  }, [chevronRotation]);

  const chevronRotate = chevronRotation.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "180deg"],
  });

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
        }}
      >
        <AppIcon
          icon={Brain02Icon}
          size={moderateScale(16, 0.5)}
          color={isStreaming ? "#a78bfa" : "#a1a1aa"}
        />
        <Text
          style={{
            fontSize: fontSize.sm,
            color: isStreaming ? "#a78bfa" : "#a1a1aa",
            fontWeight: "500",
            flex: 1,
          }}
        >
          {isExpanded ? "Hide thinking" : collapsedLabel}
        </Text>
        <Animated.View style={{ transform: [{ rotate: chevronRotate }] }}>
          <AppIcon
            icon={ArrowDown02Icon}
            size={moderateScale(14, 0.5)}
            color="#71717a"
          />
        </Animated.View>
      </PressableFeedback>

      {isExpanded ? (
        <Surface
          style={{
            backgroundColor: "rgba(39, 39, 42, 0.8)",
            borderWidth: 1,
            borderColor: "rgba(63, 63, 70, 0.6)",
            borderRadius: moderateScale(12, 0.5),
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm + 2,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#d4d4d8",
              lineHeight: 20,
            }}
          >
            {thinkingContent}
          </Text>
        </Surface>
      ) : null}
    </View>
  );
}
