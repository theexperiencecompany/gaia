import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface EmailSentData {
  to: string[];
  subject: string;
  message_id?: string;
  sent_at?: string;
}

export function EmailSentCard({ data }: { data: EmailSentData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Email Sent</Text>
        <Text className="text-foreground font-medium mb-1">
          {data.subject || "No Subject"}
        </Text>
        <Text className="text-muted text-sm">To: {data.to?.join(", ")}</Text>
      </Card.Body>
    </Card>
  );
}
