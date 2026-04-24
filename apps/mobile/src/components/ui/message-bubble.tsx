import * as Clipboard from "expo-clipboard";
import { PressableFeedback } from "heroui-native";
import type * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Animated, View } from "react-native";
import Reanimated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import { AppIcon, Copy01Icon, Tick02Icon } from "@/components/icons";
import { MarkdownRenderer } from "@/components/ui/markdown-renderer";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface CopyButtonProps {
  text: string;
}

function CopyButton({ text }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const fadeAnim = useRef(new Animated.Value(1)).current;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  const handleCopy = useCallback(async () => {
    if (copied) return;

    await Clipboard.setStringAsync(text);
    setCopied(true);

    Animated.sequence([
      Animated.timing(fadeAnim, {
        toValue: 0.3,
        duration: 100,
        useNativeDriver: true,
      }),
      Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 150,
        useNativeDriver: true,
      }),
    ]).start();

    timerRef.current = setTimeout(() => {
      setCopied(false);
    }, 2000);
  }, [copied, text, fadeAnim]);

  const { spacing } = useResponsive();

  return (
    <PressableFeedback onPress={handleCopy} style={{ padding: spacing.xs }}>
      <Animated.View style={{ opacity: fadeAnim }}>
        <AppIcon
          icon={copied ? Tick02Icon : Copy01Icon}
          size={14}
          color={copied ? "#34c759" : "rgba(255,255,255,0.35)"}
        />
      </Animated.View>
    </PressableFeedback>
  );
}

// Blinking text cursor shown at the end of a streaming message
function StreamingCursor() {
  const opacity = useSharedValue(1);

  useEffect(() => {
    opacity.value = withRepeat(
      withSequence(
        withTiming(0, { duration: 300 }),
        withTiming(1, { duration: 300 }),
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
          backgroundColor: "#ffffff",
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

  // Sent: dark pill, right-aligned
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
          backgroundColor: "rgba(28,28,32,0.95)",
          borderRadius,
          borderTopRightRadius,
          borderBottomRightRadius,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm + 2,
        }}
      >
        <Text style={{ color: "#ffffff", fontSize: fontSize.base }}>
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

  // Received: no background, plain text with action row
  const showActions =
    (grouped === "last" || grouped === "none") && !isStreaming;

  return (
    <View style={{ alignSelf: "flex-start", width: "100%" }}>
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.xs + 2,
        }}
      >
        {children ?? (
          <View style={{ flexDirection: "row", alignItems: "flex-end" }}>
            <View style={{ flex: 1 }}>
              <MarkdownRenderer content={message ?? ""} />
            </View>
            {isStreaming ? <StreamingCursor /> : null}
          </View>
        )}
      </View>

      {showActions && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingTop: spacing.xs,
          }}
        >
          <CopyButton text={message ?? ""} />
        </View>
      )}
    </View>
  );
}

export { MessageBubble };
