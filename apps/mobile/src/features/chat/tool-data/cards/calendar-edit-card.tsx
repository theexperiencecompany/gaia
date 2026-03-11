import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface CalendarEditOption {
  event_id?: string;
  title?: string;
  changes?: Record<string, unknown>;
}

function describeChanges(changes?: Record<string, unknown>): string {
  if (!changes) return "";
  const keys = Object.keys(changes);
  if (keys.length === 0) return "";
  const labels: Record<string, string> = {
    summary: "title",
    title: "title",
    start: "start time",
    end: "end time",
    location: "location",
    description: "description",
    attendees: "attendees",
  };
  const readable = keys.map((k) => labels[k] || k);
  return readable.join(", ");
}

export function CalendarEditCard({ data }: { data: CalendarEditOption[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl overflow-hidden">
      <View className="flex-row items-center px-4 py-3 border-b border-muted/20">
        <Text className="text-foreground text-sm font-medium flex-1">
          Event{data.length !== 1 ? "s" : ""} Updated
        </Text>
        <View className="bg-muted/20 rounded-full px-2 py-0.5">
          <Text className="text-muted text-xs">
            {data.length} edit{data.length !== 1 ? "s" : ""}
          </Text>
        </View>
      </View>
      <Card.Body className="p-0">
        {data.map((event, index) => {
          const changesStr = describeChanges(event.changes);
          return (
            <View key={`edit-${event.event_id || index}`}>
              {index > 0 && <View className="h-px bg-muted/10 mx-4" />}
              <View className="py-3 px-4">
                <Text
                  className="text-foreground text-sm font-medium mb-0.5"
                  numberOfLines={1}
                >
                  {event.title || "Untitled Event"}
                </Text>
                {changesStr ? (
                  <Text className="text-muted text-xs">
                    Updated: {changesStr}
                  </Text>
                ) : null}
              </View>
            </View>
          );
        })}
        {data.length === 0 && (
          <View className="px-4 py-3">
            <Text className="text-muted text-sm">No events edited</Text>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
