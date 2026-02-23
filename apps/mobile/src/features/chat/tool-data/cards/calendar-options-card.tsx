import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface CalendarOption {
  title?: string;
  start?: string;
  end?: string;
  location?: string;
  description?: string;
}

export function CalendarOptionsCard({ data }: { data: CalendarOption[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">
          Calendar Events ({data.length})
        </Text>
        {data.slice(0, 3).map((event, index) => (
          <View
            key={`event-${event.title || index}`}
            className="mb-2 last:mb-0"
          >
            <Text className="text-foreground text-sm font-medium">
              {event.title || "Untitled Event"}
            </Text>
            {event.start && (
              <Text className="text-muted text-xs">
                {new Date(event.start).toLocaleString()}
              </Text>
            )}
          </View>
        ))}
        {data.length > 3 && (
          <Text className="text-muted text-xs">
            +{data.length - 3} more events
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}
