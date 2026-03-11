import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface CalendarFetchItem {
  summary?: string;
  title?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
  location?: string;
  attendees?: Array<{ email?: string; displayName?: string }>;
  calendar_source?: string;
  organizer?: { email?: string; displayName?: string };
}

function formatEventTime(dt?: { dateTime?: string; date?: string }): string {
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

function formatEndTime(dt?: { dateTime?: string; date?: string }): string {
  if (!dt) return "";
  const raw = dt.dateTime || dt.date;
  if (!raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "";
  if (dt.date && !dt.dateTime) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

interface EventRowProps {
  event: CalendarFetchItem;
}

function EventRow({ event }: EventRowProps) {
  const title = event.summary || event.title || "Untitled Event";
  const startTime = formatEventTime(event.start);
  const endTime = formatEndTime(event.end);
  const attendeeCount = event.attendees?.length ?? 0;
  const source = event.calendar_source;

  return (
    <View className="py-3 px-4">
      <View className="flex-row items-start justify-between mb-1">
        <Text
          className="text-foreground text-sm font-medium flex-1 mr-2"
          numberOfLines={1}
        >
          {title}
        </Text>
        {source ? (
          <View className="bg-primary/15 rounded px-1.5 py-0.5">
            <Text className="text-primary text-xs" numberOfLines={1}>
              {source}
            </Text>
          </View>
        ) : null}
      </View>
      {startTime ? (
        <Text className="text-muted text-xs mb-0.5">
          {startTime}
          {endTime ? ` – ${endTime}` : ""}
        </Text>
      ) : null}
      {event.location ? (
        <Text className="text-muted text-xs mb-0.5" numberOfLines={1}>
          {event.location}
        </Text>
      ) : null}
      {attendeeCount > 0 ? (
        <Text className="text-muted text-xs">
          {attendeeCount} attendee{attendeeCount !== 1 ? "s" : ""}
        </Text>
      ) : null}
    </View>
  );
}

export function CalendarFetchCard({ data }: { data: CalendarFetchItem[] }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl overflow-hidden">
      <View className="flex-row items-center px-4 py-3 border-b border-muted/20">
        <Text className="text-foreground text-sm font-medium flex-1">
          {data.length} Event{data.length !== 1 ? "s" : ""}
        </Text>
        <Text className="text-muted text-xs">Calendar</Text>
      </View>
      <Card.Body className="p-0">
        {data.slice(0, 5).map((event, index) => (
          <View key={`event-${event.summary || event.title || index}`}>
            {index > 0 && <View className="h-px bg-muted/10 mx-4" />}
            <EventRow event={event} />
          </View>
        ))}
        {data.length > 5 && (
          <View className="px-4 py-2 border-t border-muted/10">
            <Text className="text-muted text-xs text-center">
              +{data.length - 5} more events
            </Text>
          </View>
        )}
        {data.length === 0 && (
          <View className="px-4 py-3">
            <Text className="text-muted text-sm">No events found</Text>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
