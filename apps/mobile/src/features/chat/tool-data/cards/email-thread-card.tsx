import type { EmailThreadData } from "@gaia/shared";
import type { EmailThreadItem } from "@gaia/shared/api/generated";
import { Chip } from "heroui-native";
import { View } from "react-native";
import { AppIcon, Mail01Icon } from "@/components/icons";
import { MarkdownRenderer } from "@/components/ui/markdown-renderer";
import { Text } from "@/components/ui/text";
import { CollapsibleCard } from "@/features/chat/tool-data/primitives";

/** One thread message; from_name and date only messages stored before the typed payload carry. */
export type EmailThreadMessage = EmailThreadItem & {
  from_name?: string;
  date?: string;
};

export type { EmailThreadData };

// ---------------------------------------------------------------------------
// Helpers — port of web's parseEmail + formatTime
// ---------------------------------------------------------------------------

function parseEmail(from: string | null): { name: string; email: string } {
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
  // A plain-string content carries no html/text parts; the body renders instead.
  const content = typeof message.content === "string" ? null : message.content;
  if (content?.text?.trim()) return content.text.trim();
  if (message.body?.trim()) {
    // Heuristic: if the body looks like HTML, strip it.
    if (/<\/?[a-z][\s\S]*>/i.test(message.body)) {
      return htmlToPlainText(message.body);
    }
    return message.body.trim();
  }
  if (content?.html?.trim()) return htmlToPlainText(content.html);
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
              <Text className="text-xs text-zinc-400 flex-1" numberOfLines={1}>
                {senderEmail}
              </Text>
            )}
          </View>
        </View>
        {!!timeLabel && (
          <Text className="text-xs text-zinc-400 shrink-0 ml-2">
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
  const messages: EmailThreadMessage[] = data.messages ?? [];
  const messageCount = messages.length;
  // EmailThreadCard carries no thread subject; only a card stored before it may hold one.
  const threadSubject =
    "subject" in data && typeof data.subject === "string" ? data.subject : "";

  return (
    <CollapsibleCard
      customIcon={
        <View className="w-6 h-6 rounded-md bg-white/8 items-center justify-center">
          <AppIcon icon={Mail01Icon} size={14} color="#e4e4e7" />
        </View>
      }
      title="Fetched Email Thread"
      trailing={
        messageCount > 0 ? (
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
        ) : undefined
      }
    >
      {/* Subject — mirrors the web card's header subtitle */}
      {threadSubject ? (
        <Text className="text-xs text-zinc-400 mb-2" numberOfLines={1}>
          {threadSubject}
        </Text>
      ) : null}

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
        <Text className="text-sm text-zinc-400">No messages in thread</Text>
      )}
    </CollapsibleCard>
  );
}
