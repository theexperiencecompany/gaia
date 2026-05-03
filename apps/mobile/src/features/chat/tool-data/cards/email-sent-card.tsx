import type { EmailSentData } from "@gaia/shared";
import { Chip } from "heroui-native";
import { View } from "react-native";
import { AppIcon, CheckmarkCircle02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { GmailIcon } from "./gmail-icon";

export type { EmailSentData };

// Ported 1:1 from apps/web/src/features/mail/components/EmailSentCard.tsx
function formatTime(timestamp?: string): string {
  if (!timestamp) return "Just now";

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "Just now";

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
  // Web reads only `timestamp`; backend sometimes sends `sent_at`. Same for
  // recipients (`recipients` vs `to`) and the human summary (`message` vs
  // `body`). Fall through gracefully so backend variants render correctly.
  const timestamp = data.timestamp ?? data.sent_at;
  const recipients = data.recipients ?? data.to ?? [];
  const summary = data.message ?? data.body;

  return (
    <View className="mx-4 my-1 rounded-2xl bg-green-900/20 p-4">
      {/* Header */}
      <View className="mb-3 flex-row items-center justify-between">
        <View className="flex-row items-center gap-2">
          <GmailIcon width={20} height={20} />
          <AppIcon icon={CheckmarkCircle02Icon} size={20} color="#4ade80" />
          <Text className="text-sm font-medium text-green-400">Email Sent</Text>
        </View>
        <Chip size="sm" variant="soft" color="success" animation="disable-all">
          <Chip.Label>{formatTime(timestamp)}</Chip.Label>
        </Chip>
      </View>

      {/* Email Details */}
      <View className="gap-2">
        {!!data.subject && (
          <Text className="text-sm">
            <Text className="text-zinc-400">Subject: </Text>
            <Text className="text-zinc-200">{data.subject}</Text>
          </Text>
        )}

        {recipients.length > 0 && (
          <Text className="text-sm">
            <Text className="text-zinc-400">To: </Text>
            <Text className="text-zinc-200">{recipients.join(", ")}</Text>
          </Text>
        )}

        {!!summary && (
          <Text className="text-sm font-medium text-green-400">{summary}</Text>
        )}
      </View>
    </View>
  );
}
