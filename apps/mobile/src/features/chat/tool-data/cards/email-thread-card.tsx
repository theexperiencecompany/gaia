import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface EmailThreadData {
  thread_id?: string;
  subject?: string;
  messages?: Array<{
    from?: string;
    snippet?: string;
    date?: string;
  }>;
}

export function EmailThreadCard({ data }: { data: EmailThreadData }) {
  const messageCount = data.messages?.length || 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Email Thread</Text>
        <Text className="text-foreground font-medium mb-1">
          {data.subject || "No Subject"}
        </Text>
        <Text className="text-muted text-sm">
          {messageCount} message{messageCount !== 1 ? "s" : ""}
        </Text>
      </Card.Body>
    </Card>
  );
}
