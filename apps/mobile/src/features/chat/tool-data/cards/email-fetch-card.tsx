import { Card } from "heroui-native";
import { Pressable, View } from "react-native";
import { AppIcon, Mail01Icon, MailOpen01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface EmailFetchItem {
  id?: string;
  from?: string;
  subject?: string;
  snippet?: string;
  time?: string;
  thread_id?: string;
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

function EmailRow({ email }: { email: EmailFetchItem }) {
  const senderName = email.from ? extractSenderName(email.from) : "Unknown";
  return (
    <Pressable className="flex-row items-center py-3 border-b border-white/8 active:opacity-70">
      <View className="w-28 flex-shrink-0">
        <Text className="text-sm font-medium text-foreground" numberOfLines={1}>
          {senderName}
        </Text>
      </View>
      <View className="flex-1 mx-3 min-w-0">
        <Text className="text-sm text-foreground" numberOfLines={1}>
          {email.subject || "No Subject"}
        </Text>
      </View>
      <View className="w-16 flex-shrink-0 items-end">
        <Text className="text-xs text-[#8e8e93]">{formatTime(email.time)}</Text>
      </View>
    </Pressable>
  );
}

export function EmailFetchCard({ data }: { data: EmailFetchItem[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Mail01Icon} size={14} color="#8e8e93" />
            <Text className="text-xs text-[#8e8e93]">Fetched Emails</Text>
          </View>
          <View className="rounded-full bg-white/10 px-2 py-0.5">
            <Text className="text-[10px] text-[#8e8e93]">
              {data.length} email{data.length !== 1 ? "s" : ""}
            </Text>
          </View>
        </View>

        <View className="rounded-xl bg-white/5 border border-white/8 px-3 overflow-hidden">
          {data.length === 0 ? (
            <View className="py-4 items-center">
              <AppIcon icon={MailOpen01Icon} size={20} color="#8e8e93" />
              <Text className="text-xs text-[#8e8e93] mt-2">
                No emails found
              </Text>
            </View>
          ) : (
            data.map((email, index) => (
              <View
                key={email.id || email.thread_id || `email-${index}`}
                className={index === data.length - 1 ? "border-b-0" : ""}
              >
                <EmailRow email={email} />
              </View>
            ))
          )}
        </View>
      </Card.Body>
    </Card>
  );
}
