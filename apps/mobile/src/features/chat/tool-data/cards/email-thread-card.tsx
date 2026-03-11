import { Card } from "heroui-native";
import { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import {
  AppIcon,
  ArrowDown01Icon,
  ArrowUp01Icon,
  Mail01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface EmailThreadMessage {
  id?: string;
  from?: string;
  subject?: string;
  time?: string;
  snippet?: string;
  body?: string;
  content?: { text?: string; html?: string };
}

export interface EmailThreadData {
  thread_id?: string;
  subject?: string;
  messages?: EmailThreadMessage[];
  messages_count?: number;
}

function extractSenderName(from: string): string {
  const match = from.match(/^"?([^"<]+)"?\s*</);
  if (match) return match[1].trim();
  const spaceMatch = from.match(/^([^<]+)\s+</);
  if (spaceMatch) return spaceMatch[1].trim();
  const emailMatch = from.match(/<([^>]+)>/);
  if (emailMatch) return emailMatch[1].split("@")[0];
  return from.split("@")[0] || from;
}

function extractSenderEmail(from: string): string {
  const emailMatch = from.match(/<([^>]+)>/);
  if (emailMatch) return emailMatch[1];
  if (from.includes("@")) return from;
  return "";
}

function formatTime(time?: string | null): string {
  if (!time) return "Yesterday";
  const date = new Date(time);
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

function stripHtmlTags(html: string): string {
  return html
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\s{2,}/g, " ")
    .trim();
}

function MessageItem({ message }: { message: EmailThreadMessage }) {
  const [expanded, setExpanded] = useState(false);

  const senderName = message.from ? extractSenderName(message.from) : "Unknown";
  const senderEmail = message.from ? extractSenderEmail(message.from) : "";

  const rawBody =
    message.content?.text ||
    (message.content?.html ? stripHtmlTags(message.content.html) : null) ||
    message.body ||
    message.snippet;

  return (
    <Pressable
      onPress={() => setExpanded((prev) => !prev)}
      className="py-3 border-b border-white/8 active:opacity-70"
    >
      {/* Header row */}
      <View className="flex-row items-start justify-between gap-2">
        <View className="flex-1 gap-1">
          <View className="flex-row items-center gap-2">
            <View className="rounded-full bg-white/10 px-2 py-0.5">
              <Text className="text-[10px] text-[#8e8e93]">From</Text>
            </View>
            <Text
              className="text-sm text-[#e5e5e7] font-medium"
              numberOfLines={1}
            >
              {senderName}
            </Text>
            {!!senderEmail && (
              <Text className="text-xs text-[#8e8e93] flex-1" numberOfLines={1}>
                {senderEmail}
              </Text>
            )}
          </View>
          {!!message.subject && (
            <View className="flex-row items-center gap-2">
              <View className="rounded-full bg-white/10 px-2 py-0.5">
                <Text className="text-[10px] text-[#8e8e93]">Subject</Text>
              </View>
              <Text
                className="text-sm font-medium text-[#e5e5e7]"
                numberOfLines={1}
              >
                {message.subject}
              </Text>
            </View>
          )}
        </View>
        <View className="flex-row items-center gap-1.5">
          <Text className="text-xs text-[#8e8e93]">
            {formatTime(message.time)}
          </Text>
          <AppIcon
            icon={expanded ? ArrowUp01Icon : ArrowDown01Icon}
            size={12}
            color="#8e8e93"
          />
        </View>
      </View>

      {/* Collapsed preview */}
      {!expanded && !!rawBody && (
        <Text className="text-xs text-[#8e8e93] mt-2" numberOfLines={1}>
          {rawBody}
        </Text>
      )}

      {/* Expanded body */}
      {expanded && !!rawBody && (
        <ScrollView
          className="mt-3 rounded-lg bg-white/5 p-3"
          style={{ maxHeight: 200 }}
          nestedScrollEnabled
        >
          <Text className="text-sm text-[#e5e5e7] leading-5">{rawBody}</Text>
        </ScrollView>
      )}
    </Pressable>
  );
}

export function EmailThreadCard({ data }: { data: EmailThreadData }) {
  const messages = data.messages ?? [];
  const messageCount = data.messages_count ?? messages.length;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Mail01Icon} size={14} color="#8e8e93" />
            <Text className="text-xs text-[#8e8e93]">Email Thread</Text>
          </View>
          <View className="rounded-full bg-white/10 px-2 py-0.5">
            <Text className="text-[10px] text-[#8e8e93]">
              {messageCount} message{messageCount !== 1 ? "s" : ""}
            </Text>
          </View>
        </View>

        {/* Messages */}
        <View className="rounded-xl bg-white/5 border border-white/8 px-3 overflow-hidden">
          {messages.length === 0 ? (
            <View className="py-4 items-center">
              <Text className="text-xs text-[#8e8e93]">No messages</Text>
            </View>
          ) : (
            messages.map((message, index) => (
              <View
                key={message.id || `msg-${index}`}
                className={index === messages.length - 1 ? "border-b-0" : ""}
              >
                <MessageItem message={message} />
              </View>
            ))
          )}
        </View>
      </Card.Body>
    </Card>
  );
}
