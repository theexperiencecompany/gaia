import { Accordion, Avatar, Card, Chip } from "heroui-native";
import { View } from "react-native";
import { AppIcon, Mail01Icon } from "@/components/icons";
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

interface MessageItemProps {
  message: EmailThreadMessage;
  index: number;
}

function MessageItem({ message, index }: MessageItemProps) {
  const senderName = extractFromName(message.from, message.from_name);
  const initials = senderInitials(senderName);
  const bodyText = message.body || message.snippet || "";
  const relativeDate = formatRelativeDate(message.date);

  return (
    <Accordion.Item value={`msg-${index}`} className="px-0">
      <Accordion.Trigger className="flex-row items-center gap-3 px-4 py-3">
        <Avatar alt={senderName} size="sm" className="bg-primary/20 shrink-0">
          <Avatar.Fallback className="text-primary text-xs font-semibold">
            {initials}
          </Avatar.Fallback>
        </Avatar>
        <View className="flex-1 min-w-0">
          <View className="flex-row items-center justify-between">
            <Text
              className="text-foreground text-sm font-medium flex-1 mr-2"
              numberOfLines={1}
            >
              {senderName}
            </Text>
            {!!relativeDate && (
              <Text className="text-[#8e8e93] text-xs shrink-0">
                {relativeDate}
              </Text>
            )}
          </View>
          {!!bodyText && (
            <Text className="text-[#8e8e93] text-xs mt-0.5" numberOfLines={1}>
              {bodyText}
            </Text>
          )}
        </View>
        <Accordion.Indicator iconProps={{ size: 14, color: "#8e8e93" }} />
      </Accordion.Trigger>
      <Accordion.Content className="px-4 pb-3 pt-0">
        <View className="pl-11">
          <Text className="text-foreground/80 text-sm leading-relaxed">
            {bodyText}
          </Text>
        </View>
      </Accordion.Content>
    </Accordion.Item>
  );
}

export function EmailThreadCard({ data }: { data: EmailThreadData }) {
  const messageCount = data.messages?.length || 0;

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl bg-[#171920] overflow-hidden"
    >
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center gap-2 mb-3">
          <AppIcon icon={Mail01Icon} size={14} color="#8e8e93" />
          <Text className="text-xs text-[#8e8e93] flex-1" numberOfLines={1}>
            {data.subject || "No Subject"}
          </Text>
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
        </View>

        {/* Messages accordion */}
        {messageCount > 0 ? (
          <View className="rounded-xl bg-white/5 border border-white/8 overflow-hidden">
            <Accordion isDividerVisible={true}>
              {(data.messages ?? []).map((message, index) => (
                <MessageItem
                  key={`msg-${message.from || index}-${index}`}
                  message={message}
                  index={index}
                />
              ))}
            </Accordion>
          </View>
        ) : (
          <View className="rounded-xl bg-white/5 border border-white/8 px-4 py-3">
            <Text className="text-[#8e8e93] text-sm">
              No messages in thread
            </Text>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
