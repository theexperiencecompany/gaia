import { cva, type VariantProps } from "class-variance-authority";
import { Avatar } from "heroui-native";
import type * as React from "react";
import { useEffect, useRef } from "react";
import { Animated, Pressable, View } from "react-native";
import {
  Copy01Icon,
  HugeiconsIcon,
  Message01Icon,
  Pin02Icon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { cn } from "@/lib/utils";

const GaiaLogo = require("@shared/assets/logo/gaia.png");

const messageBubbleVariants = cva("px-4 py-2.5 max-w-[100%]", {
  variants: {
    variant: {
      sent: "bg-accent self-end rounded-2xl rounded-br-md",
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
    <View className="flex-row items-center ml-2" style={{ gap: 4 }}>
      <Animated.View
        style={{
          opacity: dot1,
          width: 6,
          height: 6,
          borderRadius: 3,
          backgroundColor: "#00bbff",
        }}
      />
      <Animated.View
        style={{
          opacity: dot2,
          width: 6,
          height: 6,
          borderRadius: 3,
          backgroundColor: "#00bbff",
        }}
      />
      <Animated.View
        style={{
          opacity: dot3,
          width: 6,
          height: 6,
          borderRadius: 3,
          backgroundColor: "#00bbff",
        }}
      />
    </View>
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

  return (
    <View
      className={cn(
        "flex-row items-start gap-2",
        variant === "sent" ? "self-end" : "self-start",
      )}
    >
      {variant !== "sent" && showAvatar && (
        <Avatar
          alt="Gaia"
          size="sm"
          color="default"
          style={{ width: 24, height: 24 }}
        >
          <Avatar.Image source={GaiaLogo} />
          <Avatar.Fallback>G</Avatar.Fallback>
        </Avatar>
      )}
      {variant !== "sent" && !showAvatar && (
        <View style={{ width: 24, height: 24 }} />
      )}

      <View className={cn("flex-col", variant !== "sent" && "flex-1")}>
        <View
          {...rest}
          className={cn(
            isLoading
              ? "px-0 py-2.5"
              : messageBubbleVariants({ variant, grouped }),
            className,
          )}
        >
          {children ??
            (isLoading ? (
              <View className="flex-row items-center ">
                <Text
                  className="text-sm text-foreground"
                  style={{ lineHeight: 20 }}
                >
                  {message}
                </Text>
                <PulsingDots />
              </View>
            ) : (
              <Text
                className={cn(
                  "text-base",
                  variant === "sent"
                    ? "text-accent-foreground"
                    : "text-foreground",
                )}
              >
                {message}
              </Text>
            ))}
        </View>

        {variant === "received" &&
          !isLoading &&
          (grouped === "last" || grouped === "none") && (
            <View className="flex-row items-center gap-3 mt-1.5 px-1">
              <Pressable className="p-1 active:opacity-60">
                <HugeiconsIcon icon={Copy01Icon} size={16} color="#8e8e93" />
              </Pressable>
              <Pressable className="p-1 active:opacity-60">
                <HugeiconsIcon icon={ThumbsUpIcon} size={16} color="#8e8e93" />
              </Pressable>
              <Pressable className="p-1 active:opacity-60">
                <HugeiconsIcon
                  icon={ThumbsDownIcon}
                  size={16}
                  color="#8e8e93"
                />
              </Pressable>
              <Pressable className="p-1 active:opacity-60">
                <HugeiconsIcon icon={Pin02Icon} size={16} color="#8e8e93" />
              </Pressable>
              <Pressable className="p-1 active:opacity-60">
                <HugeiconsIcon icon={Message01Icon} size={16} color="#8e8e93" />
              </Pressable>
            </View>
          )}
      </View>
    </View>
  );
}

interface ChatMessageProps {
  timestamp?: string;
  messages: string[];
  variant?: "sent" | "received";
  className?: string;
  showTimestamp?: boolean;
}

function ChatMessage({
  timestamp,
  messages,
  variant = "received",
  className,
  showTimestamp = true,
}: ChatMessageProps) {
  const getGroupedType = (index: number, total: number) => {
    if (total === 1) return "none";
    if (index === 0) return "first";
    if (index === total - 1) return "last";
    return "middle";
  };

  return (
    <View
      className={cn(
        "flex w-full flex-col",
        variant === "sent" ? "items-end" : "items-start",
        className,
      )}
    >
      <View className="flex flex-col">
        {messages.map((message, index) => (
          <MessageBubble
            key={`${message.slice(0, 20)}-${index}`}
            message={message}
            variant={variant}
            grouped={getGroupedType(index, messages.length)}
          />
        ))}
      </View>

      {showTimestamp && timestamp && (
        <Text
          className={cn(
            "mt-1 px-2 text-xs text-muted",
            variant === "sent" && "text-right",
          )}
        >
          {timestamp}
        </Text>
      )}
    </View>
  );
}

export { MessageBubble, ChatMessage, messageBubbleVariants };
export type { MessageBubbleProps, MessageBubbleVariantProps, ChatMessageProps };
