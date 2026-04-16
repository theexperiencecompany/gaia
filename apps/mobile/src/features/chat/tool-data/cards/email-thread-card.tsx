import { useState } from "react";
import { View } from "react-native";
import { Mail01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Types --------------------------------------------------------------------

export interface EmailThreadMessage {
  id?: string;
  from?: string;
  from_name?: string;
  subject?: string;
  time?: string;
  snippet?: string;
  body?: string;
  date?: string;
  content?: { text: string; html: string };
}

export interface EmailThreadData {
  thread_id?: string;
  subject?: string;
  messages?: EmailThreadMessage[];
  messages_count?: number;
}

// -- Helpers ------------------------------------------------------------------

function formatRelativeDate(dateStr?: string): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return dateStr;
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function extractFromName(from?: string, fromName?: string): string {
  if (fromName) return fromName;
  if (!from) return "Unknown";
  const match = from.match(/^([^<]+)</);
  if (match) return match[1].trim();
  return from;
}

function senderInitials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const parts = trimmed.split(/\s+/);
  if (parts.length >= 2) {
    const first = parts[0][0] ?? "";
    const last = parts[parts.length - 1][0] ?? "";
    return `${first}${last}`.toUpperCase();
  }
  return trimmed.slice(0, 2).toUpperCase();
}

const HTML_ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'",
  "&nbsp;": " ",
};

function stripHtml(input: string): string {
  if (!input) return "";
  return input
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n\n")
    .replace(/<[^>]+>/g, "")
    .replace(
      /&(amp|lt|gt|quot|apos|nbsp|#39);/g,
      (match) => HTML_ENTITIES[match] ?? match,
    )
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function getBodyText(message: EmailThreadMessage): string {
  const htmlSource =
    message.content?.html ?? (looksLikeHtml(message.body) ? message.body : "");
  if (htmlSource) {
    const stripped = stripHtml(htmlSource);
    if (stripped) return stripped;
  }
  return (
    message.content?.text ??
    message.body ??
    message.snippet ??
    ""
  ).trim();
}

function looksLikeHtml(input?: string): boolean {
  if (!input) return false;
  return /<\/?[a-z][\s\S]*?>/i.test(input);
}

// -- Message item -------------------------------------------------------------

interface MessageItemProps {
  message: EmailThreadMessage;
}

function MessageItem({ message }: MessageItemProps) {
  const [expanded, setExpanded] = useState(false);
  const senderName = extractFromName(message.from, message.from_name);
  const initials = senderInitials(senderName);
  const bodyText = getBodyText(message);
  const relativeDate = formatRelativeDate(message.date ?? message.time);
  const previewText = bodyText.replace(/\s+/g, " ").trim();

  return (
    <ToolCardInner dense onPress={() => setExpanded((v) => !v)}>
      <View className="flex-row items-center gap-3">
        <View className="w-8 h-8 rounded-full bg-primary/20 items-center justify-center">
          <Text className="text-primary text-xs font-semibold">{initials}</Text>
        </View>
        <View className="flex-1 min-w-0">
          <View className="flex-row items-center justify-between gap-2">
            <Text
              className="text-zinc-100 text-sm font-medium flex-1"
              numberOfLines={1}
            >
              {senderName}
            </Text>
            {!!relativeDate && (
              <Text className="text-zinc-500 text-xs shrink-0">
                {relativeDate}
              </Text>
            )}
          </View>
          {!expanded && !!previewText && (
            <Text className="text-zinc-500 text-xs mt-0.5" numberOfLines={1}>
              {previewText}
            </Text>
          )}
        </View>
      </View>
      {expanded && !!bodyText && (
        <View className="mt-2 pl-11">
          <Text className="text-zinc-200 text-sm leading-relaxed">
            {bodyText}
          </Text>
        </View>
      )}
    </ToolCardInner>
  );
}

// -- Email thread card --------------------------------------------------------

export function EmailThreadCard({ data }: { data: EmailThreadData }) {
  const messages = data.messages ?? [];
  const messageCount = messages.length;
  const subject = data.subject?.trim() || "No Subject";
  const subtitle = `${messageCount} message${messageCount !== 1 ? "s" : ""}`;

  return (
    <ToolCardShell>
      <ToolCardHeader icon={Mail01Icon} title={subject} subtitle={subtitle} />

      {messageCount === 0 ? (
        <Text className="text-zinc-500 text-sm">No messages in thread</Text>
      ) : (
        <View className="gap-1.5">
          {messages.map((message, index) => (
            <MessageItem
              key={message.id ?? `${message.from ?? "msg"}-${index}`}
              message={message}
            />
          ))}
        </View>
      )}
    </ToolCardShell>
  );
}
