import { Card } from "heroui-native";
import { View } from "react-native";
import {
  AppIcon,
  CheckmarkCircle02Icon,
  Mail01Icon,
  MailSend01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface EmailSentData {
  message_id?: string;
  message?: string;
  timestamp?: string;
  recipients?: string[];
  subject?: string;
  // Legacy shape used by renderers
  to?: string[];
  sent_at?: string;
}

function formatTime(timestamp?: string): string {
  if (!timestamp) return "Just now";
  const date = new Date(timestamp);
  const now = new Date();
  const diffInSeconds = (now.getTime() - date.getTime()) / 1000;
  if (diffInSeconds < 60) return "Just now";
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

export function EmailSentCard({ data }: { data: EmailSentData }) {
  const recipients = data.recipients ?? data.to ?? [];
  const timestamp = data.timestamp ?? data.sent_at;

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl overflow-hidden"
      style={{ backgroundColor: "#0d1f0f" }}
    >
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center gap-2">
            <AppIcon icon={Mail01Icon} size={16} color="#8e8e93" />
            <AppIcon
              icon={CheckmarkCircle02Icon}
              size={16}
              color="#4ade80"
            />
            <Text className="text-sm font-medium text-green-400">
              Email Sent
            </Text>
          </View>
          <View className="rounded-full bg-green-500/15 px-2 py-0.5">
            <Text className="text-[10px] text-green-400">
              {formatTime(timestamp)}
            </Text>
          </View>
        </View>

        {/* Details */}
        <View className="gap-1.5">
          {!!data.subject && (
            <View className="flex-row gap-1">
              <Text className="text-sm text-[#8e8e93]">Subject:</Text>
              <Text className="text-sm text-[#e5e5e7] flex-1" numberOfLines={1}>
                {data.subject}
              </Text>
            </View>
          )}

          {recipients.length > 0 && (
            <View className="flex-row gap-1">
              <Text className="text-sm text-[#8e8e93]">To:</Text>
              <Text className="text-sm text-[#e5e5e7] flex-1" numberOfLines={1}>
                {recipients.join(", ")}
              </Text>
            </View>
          )}

          {!!data.message && (
            <View className="flex-row items-center gap-1.5 mt-1">
              <AppIcon icon={MailSend01Icon} size={12} color="#4ade80" />
              <Text className="text-sm font-medium text-green-400">
                {data.message}
              </Text>
            </View>
          )}
        </View>
      </Card.Body>
    </Card>
  );
}
