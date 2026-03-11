import { Button, Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface CalendarOption {
  title?: string;
  start?: string;
  end?: string;
  location?: string;
  description?: string;
  attendees?: Array<{ email?: string; displayName?: string }>;
}

interface CalendarOptionsCardProps {
  data: CalendarOption[];
  onSelect?: (index: number) => void;
}

function formatTimeRange(start?: string, end?: string): string {
  if (!start) return "";
  const startDate = new Date(start);
  if (Number.isNaN(startDate.getTime())) return start;
  const dateStr = startDate.toLocaleDateString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const startTime = startDate.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (!end) return `${dateStr}, ${startTime}`;
  const endDate = new Date(end);
  if (Number.isNaN(endDate.getTime())) return `${dateStr}, ${startTime}`;
  const endTime = endDate.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${dateStr}, ${startTime} – ${endTime}`;
}

interface OptionRowProps {
  event: CalendarOption;
  index: number;
  onSelect?: (index: number) => void;
}

function OptionRow({ event, index, onSelect }: OptionRowProps) {
  const timeRange = formatTimeRange(event.start, event.end);
  const attendeeCount = event.attendees?.length ?? 0;

  return (
    <View className="py-3 px-4">
      <Text
        className="text-foreground text-sm font-medium mb-1"
        numberOfLines={1}
      >
        {event.title || "Untitled Event"}
      </Text>
      {timeRange ? (
        <Text className="text-muted text-xs mb-1">{timeRange}</Text>
      ) : null}
      {event.location ? (
        <Text className="text-muted text-xs mb-1" numberOfLines={1}>
          {event.location}
        </Text>
      ) : null}
      {attendeeCount > 0 ? (
        <Text className="text-muted text-xs mb-2">
          {attendeeCount} attendee{attendeeCount !== 1 ? "s" : ""}
        </Text>
      ) : null}
      <Button
        variant="bordered"
        size="sm"
        className="self-start rounded-lg"
        onPress={() => onSelect?.(index)}
      >
        <Button.Label>Select this time</Button.Label>
      </Button>
    </View>
  );
}

export function CalendarOptionsCard({
  data,
  onSelect,
}: CalendarOptionsCardProps) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl overflow-hidden">
      <View className="flex-row items-center px-4 py-3 border-b border-muted/20">
        <Text className="text-foreground text-sm font-medium flex-1">
          Proposed Times
        </Text>
        <View className="bg-muted/20 rounded-full px-2 py-0.5">
          <Text className="text-muted text-xs">
            {data.length} option{data.length !== 1 ? "s" : ""}
          </Text>
        </View>
      </View>
      <Card.Body className="p-0">
        {data.map((event, index) => (
          <View key={`option-${event.title || index}-${index}`}>
            {index > 0 && <View className="h-px bg-muted/10 mx-4" />}
            <OptionRow event={event} index={index} onSelect={onSelect} />
          </View>
        ))}
        {data.length === 0 && (
          <View className="px-4 py-3">
            <Text className="text-muted text-sm">No options available</Text>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
