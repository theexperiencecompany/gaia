import { cn } from "@/lib/utils";
import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { View, Pressable } from "react-native";
import { Text } from "@/components/ui/text";
import { Avatar } from "heroui-native";
import {
  HugeiconsIcon,
  ThumbsUpIcon,
  ThumbsDownIcon,
  Pin02Icon,
  Message01Icon,
  Copy01Icon,
} from "@/components/icons";

const GaiaLogo = require("@/../assets/logo/gaia.png");

const messageBubbleVariants = cva("px-4 py-2.5 max-w-[100%]", {
  variants: {
    variant: {
      sent: "bg-accent self-end rounded-2xl rounded-br-md",
      received: "bg-surface self-start rounded-2xl rounded-bl-md",
    },
    grouped: {
      none: "",
      first: "mb-1 rounded-2xl",
      middle: "mb-1 rounded-xl",
      last: "",
    },
  },
  compoundVariants: [
    {
      variant: "sent",
      grouped: "first",
      className: "rounded-br-md",
    },
    {
      variant: "sent",
      grouped: "middle",
      className: "rounded-r-md",
    },
    {
      variant: "sent",
      grouped: "last",
      className: "rounded-tr-md",
    },
    {
      variant: "received",
      grouped: "first",
      className: "rounded-bl-md",
    },
    {
      variant: "received",
      grouped: "middle",
      className: "rounded-l-md",
    },
    {
      variant: "received",
      grouped: "last",
      className: "rounded-tl-md",
    },
  ],
  defaultVariants: {
    variant: "received",
    grouped: "none",
  },
});

type MessageBubbleVariantProps = VariantProps<typeof messageBubbleVariants>;

interface MessageBubbleProps
  extends
    React.ComponentPropsWithoutRef<typeof View>,
    MessageBubbleVariantProps {
  message?: string;
}

function MessageBubble({
  message,
  variant = "received",
  grouped = "none",
  className,
  children,
  ...props
}: MessageBubbleProps) {
  return (
    <View
      className={cn(
        "flex-row gap-2",
        variant === "received" ? "self-start" : "self-end"
      )}
    >
      {variant === "received" && (
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
      <View className="flex-col flex-1">
        <View
          className={cn(messageBubbleVariants({ variant, grouped }), className)}
          {...props}
        >
          {children || (
            <Text
              className={cn(
                "text-base",
                variant === "sent"
                  ? "text-accent-foreground"
                  : "text-foreground"
              )}
            >
              {message}
            </Text>
          )}
        </View>
        {variant === "received" && (
          <View className="flex-row items-center gap-3 mt-1.5 px-1">
            <Pressable className="p-1 active:opacity-60">
              <HugeiconsIcon icon={Copy01Icon} size={16} color="#8e8e93" />
            </Pressable>
            <Pressable className="p-1 active:opacity-60">
              <HugeiconsIcon icon={ThumbsUpIcon} size={16} color="#8e8e93" />
            </Pressable>
            <Pressable className="p-1 active:opacity-60">
              <HugeiconsIcon icon={ThumbsDownIcon} size={16} color="#8e8e93" />
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
  const hasMultipleMessages = messages.length > 1;

  const getGroupedType = (
    index: number,
    total: number
  ): "first" | "middle" | "last" | "none" => {
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
        className
      )}
    >
      <View className="flex flex-col">
        {messages.map((message, index) => (
          <MessageBubble
            key={`${message.slice(0, 20)}-${index}`}
            message={message}
            variant={variant}
            grouped={
              hasMultipleMessages
                ? getGroupedType(index, messages.length)
                : "none"
            }
          />
        ))}
      </View>

      {showTimestamp && timestamp && (
        <Text
          className={cn(
            "mt-1 px-2 text-xs text-muted",
            variant === "sent" && "text-right"
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
