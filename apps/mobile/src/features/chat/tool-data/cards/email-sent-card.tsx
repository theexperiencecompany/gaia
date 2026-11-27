import type { EmailSentData } from "@gaia/shared";
import { Chip } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { GmailIcon } from "./gmail-icon";

export type { EmailSentData };

// Ported 1:1 from apps/web/src/features/mail/components/EmailSentCard.tsx
function formatTime(timestamp: string | null | undefined): string {
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
  // Only a sent stored draft carries the send receipt; a sent compose card has just its fields.
  const receipt = "message" in data ? data : undefined;
  const recipients = ("message" in data ? data.recipients : data.to) ?? [];

  return (
    <View className="self-start mx-4 my-1 rounded-2xl bg-green-900/15 p-3.5">
      {/* Header */}
      <View className="mb-2 flex-row items-center justify-between">
        <View className="flex-row items-center gap-2">
          <GmailIcon width={20} height={20} />
          <Text className="text-sm font-medium text-green-400">Email Sent</Text>
        </View>
        <Chip size="sm" variant="soft" color="success" animation="disable-all">
          <Chip.Label>{formatTime(receipt?.timestamp)}</Chip.Label>
        </Chip>
      </View>

      {/* Email Details */}
      <View className="gap-1">
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
      </View>
    </View>
  );
}
