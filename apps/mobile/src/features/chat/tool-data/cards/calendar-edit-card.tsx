import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface CalendarEditOption {
  event_id?: string;
  title?: string;
  changes?: Record<string, unknown>;
}

export function CalendarEditCard({ data }: { data: CalendarEditOption[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Edit Events</Text>
        <Text className="text-foreground text-sm">
          {data.length} event{data.length !== 1 ? "s" : ""} to edit
        </Text>
      </Card.Body>
    </Card>
  );
}
