import type * as React from "react";
import { View } from "react-native";
import { MarkdownRenderer } from "@/components/ui/markdown-renderer";
import { Text } from "@/components/ui/text";
import { colors } from "@/lib/design-tokens";
import { useResponsive } from "@/lib/responsive";

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

  // Sent: dark pill per CHAT_STANDARDS, right-aligned
  if (variant === "sent") {
    const borderRadius = moderateScale(20, 0.5);
    const br = Math.round(borderRadius * 0.25);
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
          maxWidth: "80%",
          backgroundColor: "rgba(28,28,32,0.95)",
          borderRadius,
          borderTopRightRadius,
          borderBottomRightRadius,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
        }}
      >
        <Text
          style={{
            color: colors.white,
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

  // Received: no bubble background — plain text on canvas, full width minus
  // symmetric gutters handled here. Long-press opens the action sheet.
  const trimmed = (message ?? "").trim();
  if (!children && trimmed.length === 0 && !isStreaming) {
    return null;
  }

  return (
    <View
      style={{
        paddingHorizontal: spacing.md,
        width: "100%",
        marginVertical: 1,
      }}
    >
      {children ?? (
        <MarkdownRenderer
          content={(message ?? "").trimEnd()}
          isStreaming={isStreaming}
        />
      )}
    </View>
  );
}

export { MessageBubble };
