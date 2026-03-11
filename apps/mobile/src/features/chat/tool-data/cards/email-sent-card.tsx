import { Card } from "heroui-native";
import { View } from "react-native";
import { HugeiconsIcon, SentIcon } from "@/components/icons";
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
    <Card variant="secondary" className="mx-4 my-2 rounded-xl overflow-hidden">
      <View className="flex-row items-center gap-2 px-4 py-3 border-b border-muted/20">
        <HugeiconsIcon icon={SentIcon} size={16} color="#22c55e" />
        <Text className="text-success text-sm font-medium flex-1">
          Email Sent
        </Text>
        {sentTime ? (
          <Text className="text-muted text-xs">{sentTime}</Text>
        ) : null}
      </View>
      <Card.Body className="p-4">
        <View className="flex-row mb-2">
          <Text className="text-muted text-sm" style={{ width: 52 }}>
            To:
          </Text>
          <Text
            className="text-foreground text-sm flex-1"
            numberOfLines={2}
          >
            {toDisplay}
          </Text>
        </View>
        <View className="flex-row mb-2">
          <Text className="text-muted text-sm" style={{ width: 52 }}>
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
          <View className="mt-1 pt-2 border-t border-muted/20">
            <Text className="text-muted text-xs" numberOfLines={2}>
              {bodyPreview}
            </Text>
          </View>
        ) : null}
      </Card.Body>
    </Card>
  );
}
