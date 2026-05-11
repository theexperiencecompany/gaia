import { Card, Chip, PressableFeedback } from "heroui-native";
import { useState } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { AppIcon, ArrowDown01Icon, Mail01Icon } from "@/components/icons";
import { MarkdownRenderer } from "@/components/ui/markdown-renderer";
import { Text } from "@/components/ui/text";

// ---------------------------------------------------------------------------
// Types — mirror the web `EmailThreadData` shape from
// apps/web/src/types/features/mailTypes.ts. Fields are optional to tolerate
// loose tool output during streaming.
// ---------------------------------------------------------------------------

export interface EmailThreadMessage {
  id?: string;
  from?: string;
  /** Optional pre-parsed name (older tool output) */
  from_name?: string;
  subject?: string;
  time?: string;
  /** Older tool output exposes `date` instead of `time` */
  date?: string;
  snippet?: string;
  body?: string;
  content?: { text?: string; html?: string };
}

export interface EmailThreadData {
  thread_id?: string;
  subject?: string;
  messages?: EmailThreadMessage[];
}

// ---------------------------------------------------------------------------
// Helpers — port of web's parseEmail + formatTime
// ---------------------------------------------------------------------------

function parseEmail(from?: string): { name: string; email: string } {
  if (!from) return { name: "", email: "" };
  const match = from.match(/^(.*?)\s*<(.+?)>$/) || from.match(/(.+)/);
  if (match) {
    return {
      name: match[1] ? match[1].trim().replace(/^"|"$/g, "") : "",
      email: match[2] || "",
    };
  }
  return { name: "", email: from };
}

function formatTime(time?: string | null): string {
  if (!time) return "";
  const date = new Date(time);
  if (Number.isNaN(date.getTime())) return time;
  const now = new Date();
  const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);

  if (diffInHours < 24) {
    return date.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  }
  if (diffInHours < 48) return "Yesterday";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Strip HTML tags as a fallback when no plain text body is available. The web
 * card mounts the sanitized HTML inside a Shadow DOM iframe, which has no
 * mobile equivalent — so we render the text version through MarkdownRenderer
 * instead.
 */
function htmlToPlainText(html: string): string {
  return html
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<br\s{0,8}\/?\s{0,8}>/gi, "\n")
    .replace(/<\/p>/gi, "\n\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function getMessageText(message: EmailThreadMessage): string {
  if (message.content?.text?.trim()) return message.content.text.trim();
  if (message.body?.trim()) {
    // Heuristic: if the body looks like HTML, strip it.
    if (/<\/?[a-z][\s\S]*>/i.test(message.body)) {
      return htmlToPlainText(message.body);
    }
    return message.body.trim();
  }
  if (message.content?.html?.trim())
    return htmlToPlainText(message.content.html);
  if (message.snippet?.trim()) return message.snippet.trim();
  return "";
}

// ---------------------------------------------------------------------------
// Message item — From / Subject chip layout matches the web card
// ---------------------------------------------------------------------------

interface MessageItemProps {
  message: EmailThreadMessage;
  isLast: boolean;
}

function MessageItem({ message, isLast }: MessageItemProps) {
  const parsed = parseEmail(message.from);
  const senderName =
    message.from_name || parsed.name || parsed.email || "Unknown";
  const senderEmail = parsed.email;
  const timeLabel = formatTime(message.time ?? message.date);
  const bodyText = getMessageText(message);

  return (
    <View className={`px-4 py-3 ${isLast ? "" : "border-b border-white/8"}`}>
      {/* From row + time */}
      <View className="flex-row items-center justify-between mb-1.5">
        <View className="flex-row items-center gap-2 flex-1 min-w-0">
          <View style={{ width: 60 }}>
            <Chip
              size="sm"
              variant="secondary"
              color="default"
              className="bg-white/10"
            >
              <Chip.Label>From</Chip.Label>
            </Chip>
          </View>
          <View className="flex-row items-center gap-2 flex-1 min-w-0">
            <Text className="text-sm text-foreground/90" numberOfLines={1}>
              {senderName}
            </Text>
            {!!senderEmail && senderEmail !== senderName && (
              <Text className="text-xs text-[#8e8e93] flex-1" numberOfLines={1}>
                {senderEmail}
              </Text>
            )}
          </View>
        </View>
        {!!timeLabel && (
          <Text className="text-xs text-[#8e8e93] shrink-0 ml-2">
            {timeLabel}
          </Text>
        )}
      </View>

      {/* Subject row */}
      {!!message.subject && (
        <View className="flex-row items-center gap-2 mb-2">
          <View style={{ width: 60 }}>
            <Chip
              size="sm"
              variant="secondary"
              color="default"
              className="bg-white/10"
            >
              <Chip.Label>Subject</Chip.Label>
            </Chip>
          </View>
          <Text
            className="text-sm font-medium text-foreground/90 flex-1"
            numberOfLines={2}
          >
            {message.subject}
          </Text>
        </View>
      )}

      {/* Body — rendered through MarkdownRenderer for parity with web */}
      {!!bodyText && (
        <View className="mt-1 rounded-xl bg-white/5 border border-white/8 px-3 py-2.5">
          <MarkdownRenderer content={bodyText} />
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Main card — collapsible thread (default expanded), mirrors web Accordion
// ---------------------------------------------------------------------------

export function EmailThreadCard({ data }: { data: EmailThreadData }) {
  const [expanded, setExpanded] = useState(true);
  const messages = data.messages ?? [];
  const messageCount = messages.length;

  const rotation = useSharedValue(expanded ? 180 : 0);
  const chevronStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotation.value}deg` }],
  }));

  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    rotation.value = withTiming(next ? 180 : 0, { duration: 180 });
  };

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl bg-[#171920] overflow-hidden"
    >
      <Card.Body className="py-0 px-0">
        {/* Header — Mail01Icon + label + msg count + chevron */}
        <PressableFeedback onPress={toggle}>
          <View className="flex-row items-center gap-3 px-4 py-3">
            <View className="w-6 h-6 rounded-md bg-white/8 items-center justify-center">
              <AppIcon icon={Mail01Icon} size={14} color="#e4e4e7" />
            </View>
            <View className="flex-1 min-w-0">
              <Text
                className="text-sm font-medium text-foreground"
                numberOfLines={1}
              >
                Fetched Email Thread
              </Text>
              {!!data.subject && (
                <Text
                  className="text-xs text-[#8e8e93] mt-0.5"
                  numberOfLines={1}
                >
                  {data.subject}
                </Text>
              )}
            </View>
            {messageCount > 0 && (
              <Chip
                size="sm"
                variant="secondary"
                color="default"
                className="bg-white/10"
              >
                <Chip.Label>
                  {messageCount} msg{messageCount !== 1 ? "s" : ""}
                </Chip.Label>
              </Chip>
            )}
            <Animated.View style={chevronStyle}>
              <AppIcon
                icon={ArrowDown01Icon}
                size={14}
                color="#8e8e93"
                strokeWidth={2}
              />
            </Animated.View>
          </View>
        </PressableFeedback>

        {/* Messages — visible when expanded */}
        {expanded && (
          <View className="border-t border-white/8">
            {messageCount > 0 ? (
              messages.map((message, index) => (
                <MessageItem
                  key={
                    message.id ||
                    `msg-${message.from || index}-${message.time || index}`
                  }
                  message={message}
                  isLast={index === messageCount - 1}
                />
              ))
            ) : (
              <View className="px-4 py-3">
                <Text className="text-sm text-[#8e8e93]">
                  No messages in thread
                </Text>
              </View>
            )}
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
