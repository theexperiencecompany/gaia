import { ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import { CollapsibleCard } from "@/features/chat/tool-data/primitives";
import { GmailIcon } from "./email-fetch-card";

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

function formatTime(time?: string | null): string {
  if (!time) return "Yesterday";
  const date = new Date(time);
  if (Number.isNaN(date.getTime())) return "";
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
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

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

function resolveSender(message: EmailThreadMessage): {
  name: string;
  email: string;
} {
  const parsed = parseEmail(message.from);
  const name = parsed.name || message.from_name || "";
  const email = parsed.email || (!parsed.name ? (message.from ?? "") : "");
  return { name, email };
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

function looksLikeHtml(input?: string): boolean {
  if (!input) return false;
  return /<\/?[a-z][\s\S]*?>/i.test(input);
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

function PillLabel({ children }: { children: string }) {
  return (
    <View className="px-2 py-0.5 rounded-sm bg-zinc-700/50">
      <Text className="text-zinc-400 text-[11px] font-medium">{children}</Text>
    </View>
  );
}

function MessageItem({ message }: { message: EmailThreadMessage }) {
  const { name: senderName, email: senderEmail } = resolveSender(message);
  const time = formatTime(message.time ?? message.date);
  const bodyText = getBodyText(message);

  return (
    <View className="pb-2 mb-4 gap-1">
      <View className="flex-row items-center justify-between gap-2">
        <View className="flex-row items-center gap-2 flex-1 min-w-0">
          <View style={{ width: 60 }}>
            <PillLabel>From</PillLabel>
          </View>
          {!!senderName && (
            <Text className="text-zinc-400 text-sm shrink" numberOfLines={1}>
              {senderName}
            </Text>
          )}
          {!!senderEmail && (
            <Text
              className="text-zinc-500 text-xs font-light shrink"
              numberOfLines={1}
            >
              {senderEmail}
            </Text>
          )}
        </View>
        {!!time && (
          <Text className="text-zinc-500 text-xs shrink-0">{time}</Text>
        )}
      </View>

      {!!message.subject && (
        <View className="flex-row items-center gap-2">
          <View style={{ width: 60 }}>
            <PillLabel>Subject</PillLabel>
          </View>
          <Text
            className="text-zinc-400 text-sm font-medium flex-1"
            numberOfLines={2}
          >
            {message.subject}
          </Text>
        </View>
      )}

      {!!bodyText && (
        <View className="mt-3 rounded-xl bg-zinc-900 p-3">
          <Text className="text-zinc-200 text-sm leading-relaxed">
            {bodyText}
          </Text>
        </View>
      )}
    </View>
  );
}

export function EmailThreadCard({ data }: { data: EmailThreadData }) {
  const messages = data.messages ?? [];

  return (
    <CollapsibleCard
      customIcon={<GmailIcon width={22} height={22} />}
      title="Fetched Email Thread"
      radius="2xl"
    >
      {messages.length === 0 ? (
        <Text className="text-zinc-500 text-sm">No messages in thread</Text>
      ) : (
        <ScrollView
          style={{ maxHeight: 400 }}
          showsVerticalScrollIndicator={false}
          nestedScrollEnabled
        >
          {messages.map((message, index) => (
            <MessageItem
              key={message.id ?? `${message.from ?? "msg"}-${index}`}
              message={message}
            />
          ))}
        </ScrollView>
      )}
    </CollapsibleCard>
  );
}
