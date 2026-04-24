import { View } from "react-native";
import { AppIcon, CheckmarkCircle02Icon, Mail01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { ToolCardInner, ToolCardShell } from "../primitives";

export interface EmailSentData {
  message_id?: string;
  message: string;
  timestamp?: string;
  recipients?: string[];
  subject?: string;
}

function formatSentTime(timestamp?: string): string {
  if (!timestamp) return "Just now";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "Just now";
  const now = new Date();
  const diffSeconds = (now.getTime() - date.getTime()) / 1000;
  if (diffSeconds < 60) return "Just now";
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}m ago`;
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

export function EmailSentCard({ data }: { data: EmailSentData }) {
  const sentTime = formatSentTime(data.timestamp);
  const recipients = data.recipients?.filter(Boolean) ?? [];
  const hasRecipients = recipients.length > 0;

  return (
    <ToolCardShell>
      <View className="flex-row items-center gap-2 mb-3">
        <AppIcon icon={Mail01Icon} size={14} color="#4ade80" />
        <AppIcon icon={CheckmarkCircle02Icon} size={14} color="#4ade80" />
        <Text className="text-sm font-medium text-green-400 flex-1">
          Email Sent
        </Text>
        <View
          style={{
            paddingHorizontal: 8,
            paddingVertical: 2,
            borderRadius: 999,
            backgroundColor: "rgba(74, 222, 128, 0.1)",
          }}
        >
          <Text className="text-[10px] text-green-400 font-medium">
            {sentTime}
          </Text>
        </View>
      </View>

      <ToolCardInner>
        <View className="gap-2">
          {!!data.subject && (
            <View className="flex-row">
              <Text className="text-xs text-zinc-500" style={{ width: 64 }}>
                Subject
              </Text>
              <Text className="text-sm text-zinc-200 flex-1" numberOfLines={2}>
                {data.subject}
              </Text>
            </View>
          )}

          {hasRecipients && (
            <View className="flex-row">
              <Text className="text-xs text-zinc-500" style={{ width: 64 }}>
                To
              </Text>
              <Text className="text-sm text-zinc-200 flex-1" numberOfLines={2}>
                {recipients.join(", ")}
              </Text>
            </View>
          )}

          {!!data.message && (
            <Text className="text-sm font-medium text-green-400">
              {data.message}
            </Text>
          )}
        </View>
      </ToolCardInner>
    </ToolCardShell>
  );
}
