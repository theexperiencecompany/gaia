import type * as React from "react";
import { View } from "react-native";
import { MarkdownRenderer } from "@/components/ui/markdown-renderer";
import { Text } from "@/components/ui/text";
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

  // Received: assistant message in iMessage-style zinc-800 bubble (web parity
  // with `imessage-bubble imessage-from-them`). Long-press opens the action
  // sheet for copy/reply/etc. — no inline icons.
  const trimmed = (message ?? "").trim();
  if (!children && trimmed.length === 0 && !isStreaming) {
    return null;
  }

  const recvBorderRadius = moderateScale(20, 0.5);
  const recvBr = moderateScale(5, 0.5);
  let recvBorderTopLeftRadius = recvBorderRadius;
  let recvBorderBottomLeftRadius = recvBorderRadius;
  if (grouped === "first") recvBorderBottomLeftRadius = recvBr;
  else if (grouped === "middle") {
    recvBorderTopLeftRadius = recvBr;
    recvBorderBottomLeftRadius = recvBr;
  } else if (grouped === "last") recvBorderTopLeftRadius = recvBr;

  return (
    <View
      style={{
        paddingHorizontal: spacing.md,
        width: "100%",
        marginVertical: 1,
      }}
    >
      <View
        style={{
          alignSelf: "flex-start",
          maxWidth: "85%",
          backgroundColor: "#27272a",
          borderRadius: recvBorderRadius,
          borderTopLeftRadius: recvBorderTopLeftRadius,
          borderBottomLeftRadius: recvBorderBottomLeftRadius,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm + 2,
        }}
      >
        {children ?? <MarkdownRenderer content={(message ?? "").trimEnd()} />}
      </View>
    </View>
  );
}

export { MessageBubble };
