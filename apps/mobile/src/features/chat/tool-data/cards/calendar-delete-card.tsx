import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface CalendarDeleteOption {
  event_id?: string;
  title?: string;
  start?: { dateTime?: string; date?: string };
}

function formatDeletedTime(dt?: { dateTime?: string; date?: string }): string {
  if (!dt) return "";
  const raw = dt.dateTime || dt.date;
  if (!raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  if (dt.date && !dt.dateTime) {
    return date.toLocaleDateString([], {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  }
  return date.toLocaleString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function CalendarDeleteCard({ data }: { data: CalendarDeleteOption[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl overflow-hidden">
      <View className="flex-row items-center px-4 py-3 border-b border-muted/20">
        <Text className="text-foreground text-sm font-medium flex-1">
          Event{data.length !== 1 ? "s" : ""} Deleted
        </Text>
        <View className="bg-danger/15 rounded-full px-2 py-0.5">
          <Text className="text-danger text-xs">{data.length} removed</Text>
        </View>
      </View>
      <Card.Body className="p-0">
        {data.map((event, index) => {
          const timeStr = formatDeletedTime(event.start);
          return (
            <View key={`delete-${event.event_id || index}`}>
              {index > 0 && <View className="h-px bg-muted/10 mx-4" />}
              <View className="py-3 px-4">
                <Text
                  className="text-foreground/70 text-sm font-medium line-through mb-0.5"
                  numberOfLines={1}
                >
                  {event.title || "Untitled Event"}
                </Text>
                {timeStr ? (
                  <Text className="text-muted text-xs">{timeStr}</Text>
                ) : null}
              </View>
            </View>
          );
        })}
        {data.length === 0 && (
          <View className="px-4 py-3">
            <Text className="text-muted text-sm">No events deleted</Text>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
