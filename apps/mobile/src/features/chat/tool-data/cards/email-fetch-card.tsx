import { Pressable, View } from "react-native";
import { AppIcon, Mail01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface EmailFetchItem {
  from?: string;
  from_name?: string;
  subject?: string;
  snippet?: string;
  date?: string;
  is_unread?: boolean;
}

function formatRelativeDate(dateStr?: string): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return dateStr;
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);
  if (diffHours < 24) {
    return date.toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  }
  if (diffHours < 48) return "Yesterday";
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function extractFromName(from?: string, fromName?: string): string {
  if (fromName) return fromName;
  if (!from) return "Unknown";
  const match = from.match(/^"?([^"<]+)"?\s*</);
  if (match) return match[1].trim();
  return from;
}

interface EmailRowProps {
  email: EmailFetchItem;
  onOpenThread?: () => void;
}

function EmailRow({ email, onOpenThread }: EmailRowProps) {
  const senderName = extractFromName(email.from, email.from_name);
  const relativeDate = formatRelativeDate(email.date);

  return (
    <Pressable onPress={onOpenThread} className="rounded-2xl bg-zinc-900 p-3">
      <View className="flex-row items-start">
        <View className="mr-3 mt-1.5 w-2">
          {email.is_unread ? (
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                backgroundColor: "#00bbff",
              }}
            />
          ) : null}
        </View>
        <View className="flex-1 min-w-0">
          <View className="flex-row items-center justify-between mb-0.5">
            <Text
              className={`text-sm flex-1 mr-2 ${email.is_unread ? "text-zinc-100 font-semibold" : "text-zinc-100"}`}
              numberOfLines={1}
            >
              {senderName}
            </Text>
            {!!relativeDate && (
              <Text className="text-xs text-zinc-500 shrink-0">
                {relativeDate}
              </Text>
            )}
          </View>
          <Text
            className={`text-sm mb-0.5 ${email.is_unread ? "text-zinc-100 font-medium" : "text-zinc-400"}`}
            numberOfLines={1}
          >
            {email.subject || "No Subject"}
          </Text>
          {!!email.snippet && (
            <Text className="text-xs text-zinc-500" numberOfLines={2}>
              {email.snippet}
            </Text>
          )}
        </View>
      </View>
    </Pressable>
  );
}

export function EmailFetchCard({ data }: { data: EmailFetchItem[] }) {
  const unreadCount = data.filter((e) => e.is_unread).length;
  const visible = data.slice(0, 5);
  const overflow = data.length - visible.length;

  return (
    <View className="mx-4 my-2 rounded-2xl bg-zinc-800 p-4">
      <View className="flex-row items-center gap-2 mb-3">
        <AppIcon icon={Mail01Icon} size={14} color="#a1a1aa" />
        <Text className="text-xs text-zinc-400 flex-1">
          {data.length} Email{data.length !== 1 ? "s" : ""}
        </Text>
        {unreadCount > 0 && (
          <View
            style={{
              paddingHorizontal: 8,
              paddingVertical: 2,
              borderRadius: 999,
              backgroundColor: "rgba(0, 187, 255, 0.15)",
            }}
          >
            <Text className="text-[10px] text-[#00bbff] font-medium">
              {unreadCount} unread
            </Text>
          </View>
        )}
      </View>
      <View className="gap-2">
        {visible.map((email, index) => (
          <EmailRow
            key={`email-${email.subject || ""}-${email.date || ""}-${index}`}
            email={email}
          />
        ))}
        {overflow > 0 && (
          <View className="rounded-2xl bg-zinc-900 p-3">
            <Text className="text-xs text-zinc-500 text-center">
              +{overflow} more email{overflow !== 1 ? "s" : ""}
            </Text>
          </View>
        )}
      </View>
    </View>
  );
}
