import * as Clipboard from "expo-clipboard";
import { PressableFeedback } from "heroui-native";
import type * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Animated, View } from "react-native";
import {
  AppIcon,
  Copy01Icon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  Tick02Icon,
} from "@/components/icons";
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

export interface MessageBubbleProps {
  message?: string;
  variant?: "sent" | "received" | "loading";
  grouped?: "none" | "first" | "middle" | "last";
  showAvatar?: boolean;
  children?: React.ReactNode;
}

function MessageBubble({
  message,
  variant = "received",
  grouped = "none",
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
          maxWidth: "80%",
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
  const showActions = grouped === "last" || grouped === "none";

  return (
    <View style={{ alignSelf: "flex-start", width: "100%" }}>
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.xs + 2,
        }}
      >
        {children ?? <MarkdownRenderer content={message ?? ""} />}
      </View>

      {showActions && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingTop: spacing.xs,
            gap: moderateScale(20, 0.5),
          }}
        >
          <CopyButton text={message ?? ""} />
          <PressableFeedback style={{ padding: spacing.xs }}>
            <AppIcon
              icon={ThumbsUpIcon}
              size={14}
              color="rgba(255,255,255,0.35)"
            />
          </PressableFeedback>
          <PressableFeedback style={{ padding: spacing.xs }}>
            <AppIcon
              icon={ThumbsDownIcon}
              size={14}
              color="rgba(255,255,255,0.35)"
            />
          </PressableFeedback>
        </View>
      )}
    </View>
  );
}

export { MessageBubble };
