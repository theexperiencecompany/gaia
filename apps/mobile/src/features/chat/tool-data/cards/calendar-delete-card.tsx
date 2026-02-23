import { Card } from "heroui-native";
import { Text } from "@/components/ui/text";

export interface CalendarDeleteOption {
  event_id?: string;
  title?: string;
}

export function CalendarDeleteCard({ data }: { data: CalendarDeleteOption[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-1">Delete Events</Text>
        <Text className="text-foreground text-sm">
          {data.length} event{data.length !== 1 ? "s" : ""} to delete
        </Text>
      </Card.Body>
    </Card>
  );
}
