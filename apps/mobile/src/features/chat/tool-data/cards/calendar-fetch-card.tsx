import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface CalendarFetchItem {
  summary?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
}

export function CalendarFetchCard({ data }: { data: CalendarFetchItem[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <Text className="text-xs text-muted mb-2">
          Fetched Events ({data.length})
        </Text>
        {data.slice(0, 3).map((event, index) => (
          <View
            key={`fetch-${event.summary || index}`}
            className="mb-2 last:mb-0"
          >
            <Text className="text-foreground text-sm">
              {event.summary || "Untitled Event"}
            </Text>
            <Text className="text-muted text-xs">
              {event.start?.dateTime || event.start?.date || "No date"}
            </Text>
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}
