import type * as React from "react";
import { useEffect } from "react";
import { View } from "react-native";
import Reanimated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import { MarkdownRenderer } from "@/components/ui/markdown-renderer";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

// Blinking text cursor shown at the end of a streaming message
function StreamingCursor() {
  const opacity = useSharedValue(1);

  useEffect(() => {
    opacity.value = withRepeat(
      withSequence(
        withTiming(0, { duration: 450 }),
        withTiming(1, { duration: 450 }),
      ),
      -1,
      false,
    );
  }, [opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <Reanimated.View
      style={[
        animatedStyle,
        {
          width: 2,
          height: 16,
          backgroundColor: "rgba(255,255,255,0.75)",
          borderRadius: 1,
          marginLeft: 2,
          alignSelf: "flex-end",
          marginBottom: 1,
        },
      ]}
    />
  );
}

export interface MessageBubbleProps {
  message?: string;
  variant?: "sent" | "received" | "loading";
  grouped?: "none" | "first" | "middle" | "last";
  showAvatar?: boolean;
  isStreaming?: boolean;
  children?: React.ReactNode;
}

function MessageBubble({
  message,
  variant = "received",
  grouped = "none",
  isStreaming = false,
  children,
}: MessageBubbleProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  // Sent: brand cyan pill, right-aligned
  if (variant === "sent") {
    const borderRadius = moderateScale(20, 0.5);
    const br = moderateScale(5, 0.5);
    let borderTopRightRadius = borderRadius;
    let borderBottomRightRadius = borderRadius;
    if (grouped === "first") borderBottomRightRadius = br;
    else if (grouped === "middle") {
      borderTopRightRadius = br;
      borderBottomRightRadius = br;
    } else if (grouped === "last") borderTopRightRadius = br;

    return (
      <View
        style={{
          alignSelf: "flex-end",
          backgroundColor: "#00bbff",
          borderRadius,
          borderTopRightRadius,
          borderBottomRightRadius,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
        }}
      >
        <Text
          style={{
            color: "#000000",
            fontSize: fontSize.base,
            lineHeight: Math.round(fontSize.base * 1.5),
          }}
        >
          {children ?? message}
        </Text>
      </View>
    );
  }

  // Loading state
  if (variant === "loading") {
    return (
      <View
        style={{ paddingHorizontal: spacing.md, paddingVertical: spacing.xs }}
      >
        {children}
      </View>
    );
  }

  // Received: assistant message renders as plain prose (web parity).
  // No bubble background, no inline copy button — long-press surfaces
  // the action sheet with all options including copy.
  const trimmed = (message ?? "").trim();
  if (!children && trimmed.length === 0 && !isStreaming) {
    return null;
  }

  return (
    <View style={{ paddingHorizontal: spacing.md, width: "100%" }}>
      {children ?? (
        <View style={{ flexDirection: "row", alignItems: "flex-end" }}>
          <View style={{ flex: 1 }}>
            <MarkdownRenderer content={message ?? ""} />
          </View>
          {isStreaming ? <StreamingCursor /> : null}
        </View>
      )}
    </View>
  );
}

export { MessageBubble };
