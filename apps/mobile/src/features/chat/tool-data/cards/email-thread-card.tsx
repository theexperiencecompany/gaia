import { Card } from "heroui-native";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { HugeiconsIcon, Mail01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface EmailThreadMessage {
  from?: string;
  from_name?: string;
  body?: string;
  snippet?: string;
  date?: string;
}

export interface EmailThreadData {
  thread_id?: string;
  subject?: string;
  messages?: EmailThreadMessage[];
}

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
  const parts = name.trim().split(" ");
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

interface MessageRowProps {
  message: EmailThreadMessage;
  index: number;
}

function MessageRow({ message, index }: MessageRowProps) {
  const [expanded, setExpanded] = useState(index === 0);
  const senderName = extractFromName(message.from, message.from_name);
  const initials = senderInitials(senderName);
  const bodyText = message.body || message.snippet || "";

  return (
    <Pressable
      onPress={() => setExpanded((prev) => !prev)}
      className="px-4 py-3 active:bg-muted/10"
    >
      <View className="flex-row items-start gap-3">
        <View className="w-8 h-8 rounded-full bg-primary/20 items-center justify-center shrink-0">
          <Text className="text-primary text-xs font-semibold">{initials}</Text>
        </View>
        <View className="flex-1 min-w-0">
          <View className="flex-row items-center justify-between mb-0.5">
            <Text
              className="text-foreground text-sm font-medium"
              numberOfLines={1}
            >
              {senderName}
            </Text>
            <Text className="text-muted text-xs ml-2 shrink-0">
              {formatRelativeDate(message.date)}
            </Text>
          </View>
          {expanded ? (
            <Text className="text-foreground/80 text-sm leading-relaxed">
              {bodyText}
            </Text>
          ) : (
            <Text className="text-muted text-xs" numberOfLines={1}>
              {bodyText}
            </Text>
          )}
        </View>
      </View>
    </Pressable>
  );
}

export function EmailThreadCard({ data }: { data: EmailThreadData }) {
  const messageCount = data.messages?.length || 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl overflow-hidden">
      <View className="flex-row items-center gap-2 px-4 py-3 border-b border-muted/20">
        <HugeiconsIcon icon={Mail01Icon} size={16} color="#6b6b6b" />
        <Text
          className="text-foreground text-sm font-medium flex-1"
          numberOfLines={1}
        >
          {data.subject || "No Subject"}
        </Text>
        <View className="bg-muted/20 rounded-full px-2 py-0.5">
          <Text className="text-muted text-xs">
            {messageCount} msg{messageCount !== 1 ? "s" : ""}
          </Text>
        </View>
      </View>
      <Card.Body className="p-0">
        {data.messages?.map((message, index) => (
          <View key={`msg-${message.from || index}-${index}`}>
            {index > 0 && <View className="h-px bg-muted/10 mx-4" />}
            <MessageRow message={message} index={index} />
          </View>
        ))}
        {messageCount === 0 && (
          <View className="px-4 py-3">
            <Text className="text-muted text-sm">No messages in thread</Text>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
