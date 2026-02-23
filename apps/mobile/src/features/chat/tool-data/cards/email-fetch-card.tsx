import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface EmailFetchItem {
  from?: string;
  subject?: string;
  snippet?: string;
  date?: string;
}

export function EmailFetchCard({ data }: { data: EmailFetchItem[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">Emails ({data.length})</Text>
        {data.slice(0, 3).map((email, index) => (
          <View
            key={`email-${email.subject || index}`}
            className="mb-2 last:mb-0"
          >
            <Text className="text-foreground text-sm" numberOfLines={1}>
              {email.subject || "No Subject"}
            </Text>
            <Text className="text-muted text-xs" numberOfLines={1}>
              {email.from}
            </Text>
          </View>
        ))}
        {data.length > 3 && (
          <Text className="text-muted text-xs">
            +{data.length - 3} more emails
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}
