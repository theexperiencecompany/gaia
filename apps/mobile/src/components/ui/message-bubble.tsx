import { cva, type VariantProps } from "class-variance-authority";
import * as Clipboard from "expo-clipboard";
import { Avatar, PressableFeedback } from "heroui-native";
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
import { cn } from "@/lib/utils";

const GaiaLogo = require("@shared/assets/logo/gaia.png");

const messageBubbleVariants = cva("px-4 py-3 max-w-[100%]", {
  variants: {
    variant: {
      sent: "self-end rounded-2xl rounded-br-md",
      received: "bg-surface self-start rounded-2xl rounded-bl-md",
      loading: "bg-transparent self-start",
    },
    grouped: {
      none: "",
      first: "mb-1 rounded-2xl",
      middle: "mb-1 rounded-xl",
      last: "",
    },
  },
  compoundVariants: [
    { variant: "sent", grouped: "first", className: "rounded-br-md" },
    { variant: "sent", grouped: "middle", className: "rounded-r-md" },
    { variant: "sent", grouped: "last", className: "rounded-tr-md" },
    { variant: "received", grouped: "first", className: "rounded-bl-md" },
    { variant: "received", grouped: "middle", className: "rounded-l-md" },
    { variant: "received", grouped: "last", className: "rounded-tl-md" },
  ],
  defaultVariants: {
    variant: "received",
    grouped: "none",
  },
});

type MessageBubbleVariantProps = VariantProps<typeof messageBubbleVariants>;

function PulsingDots() {
  const { moderateScale, spacing } = useResponsive();
  const dotSize = moderateScale(6, 0.5);

  const dot1 = useRef(new Animated.Value(0.3)).current;
  const dot2 = useRef(new Animated.Value(0.3)).current;
  const dot3 = useRef(new Animated.Value(0.3)).current;

  useEffect(() => {
    const animate = (dot: Animated.Value, delay: number) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(delay),
          Animated.timing(dot, {
            toValue: 1,
            duration: 400,
            useNativeDriver: true,
          }),
          Animated.timing(dot, {
            toValue: 0.3,
            duration: 400,
            useNativeDriver: true,
          }),
        ]),
      );

    const a1 = animate(dot1, 0);
    const a2 = animate(dot2, 150);
    const a3 = animate(dot3, 300);

    a1.start();
    a2.start();
    a3.start();

    return () => {
      dot1.stopAnimation();
      dot2.stopAnimation();
      dot3.stopAnimation();
    };
  }, [dot1, dot2, dot3]);

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        marginLeft: spacing.sm,
        gap: moderateScale(4, 0.5),
      }}
    >
      <Animated.View
        style={{
          opacity: dot1,
          width: dotSize,
          height: dotSize,
          borderRadius: dotSize / 2,
          backgroundColor: "#00bbff",
        }}
      />
      <Animated.View
        style={{
          opacity: dot2,
          width: dotSize,
          height: dotSize,
          borderRadius: dotSize / 2,
          backgroundColor: "#00bbff",
        }}
      />
      <Animated.View
        style={{
          opacity: dot3,
          width: dotSize,
          height: dotSize,
          borderRadius: dotSize / 2,
          backgroundColor: "#00bbff",
        }}
      />
    </View>
  );
}

interface CopyButtonProps {
  text: string;
  iconSize: number;
  padding: number;
}

function CopyButton({ text, iconSize, padding }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const fadeAnim = useRef(new Animated.Value(1)).current;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup timeout on unmount to prevent setState after unmount
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

    // Simple fade out and in
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

    // Reset after 2 seconds
    timerRef.current = setTimeout(() => {
      setCopied(false);
    }, 2000);
  }, [copied, text, fadeAnim]);

  return (
    <PressableFeedback onPress={handleCopy} style={{ padding }}>
      <Animated.View style={{ opacity: fadeAnim }}>
        <AppIcon
          icon={copied ? Tick02Icon : Copy01Icon}
          size={iconSize}
          color={copied ? "#34c759" : "#8e8e93"}
        />
      </Animated.View>
    </PressableFeedback>
  );
}

interface MessageBubbleProps
  extends React.ComponentPropsWithoutRef<typeof View>,
    MessageBubbleVariantProps {
  message?: string;
  showAvatar?: boolean;
}

function MessageBubble({
  message,
  variant = "received",
  grouped = "none",
  showAvatar = true,
  className,
  children,
  ...rest
}: MessageBubbleProps) {
  const isLoading = variant === "loading";
  const { spacing, iconSize, fontSize, moderateScale } = useResponsive();
  const avatarSize = moderateScale(24, 0.5);

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.sm,
        alignSelf: variant === "sent" ? "flex-end" : "flex-start",
      }}
    >
      {variant !== "sent" && showAvatar && (
        <Avatar
          alt="Gaia"
          size="sm"
          color="default"
          style={{ width: avatarSize, height: avatarSize }}
        >
          <Avatar.Image source={GaiaLogo} />
          <Avatar.Fallback>G</Avatar.Fallback>
        </Avatar>
      )}
      {variant !== "sent" && !showAvatar && (
        <View style={{ width: avatarSize, height: avatarSize }} />
      )}

      <View className={cn("flex-col", variant !== "sent" && "flex-1")}>
        <View
          {...rest}
          style={
            variant === "sent"
              ? {
                  backgroundColor: "rgba(0,187,255,0.12)",
                  borderWidth: 1,
                  borderColor: "rgba(0,187,255,0.12)",
                }
              : undefined
          }
          className={cn(
            isLoading
              ? "px-0 py-2.5"
              : messageBubbleVariants({ variant, grouped }),
            className,
          )}
        >
          {children ??
            (isLoading ? (
              <View style={{ flexDirection: "row", alignItems: "center" }}>
                <Text style={{ fontSize: fontSize.sm, lineHeight: 20 }}>
                  {message}
                </Text>
                <PulsingDots />
              </View>
            ) : variant === "received" ? (
              <MarkdownRenderer content={message ?? ""} />
            ) : (
              <Text className={cn("text-base", "text-white")}>{message}</Text>
            ))}
        </View>

        {variant === "received" &&
          !isLoading &&
          (grouped === "last" || grouped === "none") && (
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.md,
                marginTop: spacing.xs,
                paddingHorizontal: spacing.xs,
              }}
            >
              <CopyButton
                text={message || ""}
                iconSize={iconSize.sm}
                padding={spacing.xs}
              />
              <PressableFeedback style={{ padding: spacing.xs }}>
                <AppIcon
                  icon={ThumbsUpIcon}
                  size={iconSize.sm}
                  color="#8e8e93"
                />
              </PressableFeedback>
              <PressableFeedback style={{ padding: spacing.xs }}>
                <AppIcon
                  icon={ThumbsDownIcon}
                  size={iconSize.sm}
                  color="#8e8e93"
                />
              </PressableFeedback>
            </View>
          )}
      </View>
    </View>
  );
}

export { MessageBubble, messageBubbleVariants };
export type { MessageBubbleProps, MessageBubbleVariantProps };
