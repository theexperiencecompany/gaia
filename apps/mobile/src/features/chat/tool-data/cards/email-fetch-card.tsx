import { View } from "react-native";
import Svg, { Path } from "react-native-svg";
import { Text } from "@/components/ui/text";
import { CollapsibleCard } from "@/features/chat/tool-data/primitives";

export interface EmailFetchItem {
  id?: string;
  thread_id?: string;
  from?: string;
  from_name?: string;
  subject?: string;
  snippet?: string;
  time?: string;
  date?: string;
  is_unread?: boolean;
}

export function GmailIcon({
  width = 20,
  height = 20,
}: {
  width?: number;
  height?: number;
}) {
  return (
    <Svg width={width} height={height} viewBox="0 0 256 193">
      <Path
        d="M58.182 192.05V93.14L27.507 65.077L0 49.504v125.091c0 9.658 7.825 17.455 17.455 17.455z"
        fill="#4285f4"
      />
      <Path
        d="M197.818 192.05h40.727c9.659 0 17.455-7.826 17.455-17.455V49.505l-31.156 17.837l-27.026 25.798z"
        fill="#34a853"
      />
      <Path
        d="m58.182 93.14l-4.174-38.647l4.174-36.989L128 69.868l69.818-52.364l4.669 34.992l-4.669 40.644L128 145.504z"
        fill="#ea4335"
      />
      <Path
        d="M197.818 17.504V93.14L256 49.504V26.231c0-21.585-24.64-33.89-41.89-20.945z"
        fill="#fbbc04"
      />
      <Path
        d="m0 49.504l26.759 20.07L58.182 93.14V17.504L41.89 5.286C24.61-7.66 0 4.646 0 26.23z"
        fill="#c5221f"
      />
    </Svg>
  );
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

function formatTime(time: string | null | undefined): string {
  if (!time) return "";

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

function EmailRow({
  email,
  isLast,
}: {
  email: EmailFetchItem;
  isLast: boolean;
}) {
  const senderName = extractSenderName(email.from || "Unknown Sender");
  const subject = email.subject || "Unknown Subject";
  const timeLabel = formatTime(email.time ?? email.date ?? null);

  return (
    <View
      className={`flex-row items-center gap-4 p-3${isLast ? "" : " border-b border-zinc-700"}`}
    >
      <View className="w-40 flex-shrink-0">
        <Text className="text-zinc-300 text-sm font-medium" numberOfLines={1}>
          {senderName}
        </Text>
      </View>
      <View className="flex-1 min-w-0">
        <Text className="text-white text-sm" numberOfLines={1}>
          {subject}
        </Text>
      </View>
      {!!timeLabel && (
        <Text className="text-zinc-400 text-xs">{timeLabel}</Text>
      )}
    </View>
  );
}

export function EmailFetchCard({ data }: { data: EmailFetchItem[] }) {
  const count = data.length;
  const plural = count === 1 ? "" : "s";

  return (
    <CollapsibleCard
      customIcon={<GmailIcon width={20} height={20} />}
      title={(open) => `${open ? "Hide" : "Show"} ${count} Email${plural}`}
      titleTone="muted"
      radius="3xl"
    >
      {count > 0 ? (
        <View>
          {data.map((email, index) => (
            <EmailRow
              key={email.id ?? email.thread_id ?? `email-${index}`}
              email={email}
              isLast={index === count - 1}
            />
          ))}
        </View>
      ) : (
        <Text className="py-3 text-zinc-500 text-sm">No emails found</Text>
      )}
    </CollapsibleCard>
  );
}
