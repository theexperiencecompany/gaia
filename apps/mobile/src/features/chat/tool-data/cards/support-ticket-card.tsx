import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface SupportTicketData {
  type?: string;
  title?: string;
  description?: string;
}

export function SupportTicketCard({ data }: { data: SupportTicketData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">
          {data.type === "feature" ? "Feature Request" : "Support Ticket"}
        </Text>
        <Text className="text-foreground font-medium mb-1">
          {data.title || "No Title"}
        </Text>
        {data.description && (
          <Text className="text-muted text-sm" numberOfLines={2}>
            {data.description}
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}
