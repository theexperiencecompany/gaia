import { Card, Chip, Divider } from "heroui-native";
import { View } from "react-native";
import { AppIcon, SentIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";

export interface EmailSentData {
  to: string[];
  subject: string;
  body?: string;
  message_id?: string;
  sent_at?: string;
}

function formatSentTime(dateStr?: string): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return dateStr;
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function EmailSentCard({ data }: { data: EmailSentData }) {
  const sentTime = formatSentTime(data.sent_at);
  const toDisplay = data.to?.join(", ") || "";
  const bodyPreview = data.body?.split("\n").find((l) => l.trim()) || "";

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl bg-[#171920] overflow-hidden"
    >
      <Card.Body className="py-0 px-0">
        {/* Header */}
        <View className="flex-row items-center gap-2 px-4 py-3">
          <View className="rounded-full p-1.5 bg-green-500/15">
            <AppIcon icon={SentIcon} size={13} color="#4ade80" />
          </View>
          <Text className="text-sm font-medium text-green-400 flex-1">
            Email Sent
          </Text>
          {sentTime ? (
            <Chip
              size="sm"
              variant="secondary"
              color="default"
              className="bg-white/10"
            >
              <Chip.Label>{sentTime}</Chip.Label>
            </Chip>
          ) : null}
        </View>

        <Divider className="bg-white/8" />

        {/* Body */}
        <View className="px-4 py-3 gap-2">
          <View className="flex-row">
            <Text className="text-[#8e8e93] text-sm" style={{ width: 52 }}>
              To:
            </Text>
            <Text className="text-foreground text-sm flex-1" numberOfLines={2}>
              {toDisplay}
            </Text>
          </View>
          <View className="flex-row">
            <Text className="text-[#8e8e93] text-sm" style={{ width: 52 }}>
              Subject:
            </Text>
            <Text
              className="text-foreground text-sm font-medium flex-1"
              numberOfLines={1}
            >
              {data.subject || "No Subject"}
            </Text>
          </View>
          {bodyPreview ? (
            <>
              <Divider className="bg-white/8" />
              <Text className="text-[#8e8e93] text-xs" numberOfLines={2}>
                {bodyPreview}
              </Text>
            </>
          ) : null}
        </View>
      </Card.Body>
    </Card>
  );
}
