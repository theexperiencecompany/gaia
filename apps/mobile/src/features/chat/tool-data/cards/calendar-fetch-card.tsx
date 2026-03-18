import { Card, Chip, PressableFeedback } from "heroui-native";
import { ScrollView, View } from "react-native";
import { AppIcon, Calendar03Icon, Clock01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Types --------------------------------------------------------------------

export interface CalendarFetchItem {
  summary?: string;
  title?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
  location?: string;
  attendees?: Array<{ email?: string; displayName?: string }>;
  calendar_source?: string;
  calendar_name?: string;
  background_color?: string;
  organizer?: { email?: string; displayName?: string };
}

interface CalendarFetchCardProps {
  data: CalendarFetchItem[];
  onEventPress?: (event: CalendarFetchItem, index: number) => void;
}

// -- Helpers ------------------------------------------------------------------

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

// -- Event row ----------------------------------------------------------------

interface EventRowProps {
  event: CalendarFetchItem;
  onPress?: () => void;
}

function EventRow({ event, onPress }: EventRowProps) {
  const title = event.summary ?? event.title ?? "Untitled Event";
  const startTime = formatEventTime(event.start);
  const endTime = formatEndTime(event.end);
  const attendeeCount = event.attendees?.length ?? 0;
  const calendarLabel = event.calendar_source ?? event.calendar_name;
  const eventColor = event.background_color ?? "#00bbff";

  const content = (
    <View className="py-3 px-4 flex-row items-start gap-3">
      {/* Color indicator */}
      <View
        className="w-1.5 self-stretch rounded-full mt-1 flex-shrink-0"
        style={{ backgroundColor: eventColor }}
      />

      {/* Info */}
      <View className="flex-1 min-w-0">
        <View className="flex-row items-start justify-between gap-2 mb-0.5">
          <Text
            className="text-sm font-medium text-foreground flex-1"
            numberOfLines={1}
          >
            {title}
          </Text>
          {calendarLabel ? (
            <Chip
              size="sm"
              variant="soft"
              className="flex-shrink-0"
              animation="disable-all"
            >
              <Chip.Label numberOfLines={1}>{calendarLabel}</Chip.Label>
            </Chip>
          ) : null}
        </View>

        {startTime ? (
          <View className="flex-row items-center gap-1 mb-0.5">
            <AppIcon icon={Clock01Icon} size={11} color="#8e8e93" />
            <Text className="text-muted text-xs">
              {startTime}
              {endTime ? ` – ${endTime}` : ""}
            </Text>
          </View>
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
    </View>
  );

  if (onPress) {
    return <PressableFeedback onPress={onPress}>{content}</PressableFeedback>;
  }

  return content;
}

// -- Calendar fetch card ------------------------------------------------------

const MAX_VISIBLE = 5;

export function CalendarFetchCard({
  data,
  onEventPress,
}: CalendarFetchCardProps) {
  const visibleEvents = data.slice(0, MAX_VISIBLE);
  const overflow = data.length - MAX_VISIBLE;

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl bg-[#171920] overflow-hidden"
      animation="disable-all"
    >
      {/* Header */}
      <Card.Header className="px-4 py-3 pb-0">
        <View className="flex-row items-center gap-2">
          <View className="w-7 h-7 rounded-xl bg-primary/15 items-center justify-center">
            <AppIcon icon={Calendar03Icon} size={14} color="#00bbff" />
          </View>
          <View className="flex-1 min-w-0">
            <Card.Title>
              {data.length} Event{data.length !== 1 ? "s" : ""}
            </Card.Title>
          </View>
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
          >
            <Chip.Label>Calendar</Chip.Label>
          </Chip>
        </View>
      </Card.Header>

      <Card.Body className="p-0">
        <View
          style={{
            height: 1,
            backgroundColor: "rgba(255,255,255,0.07)",
            marginTop: 12,
          }}
        />

        {data.length === 0 ? (
          <View className="px-4 py-3">
            <Text className="text-muted text-sm">No events found</Text>
          </View>
        ) : (
          <ScrollView
            style={{ maxHeight: 380 }}
            nestedScrollEnabled
            showsVerticalScrollIndicator={false}
          >
            {visibleEvents.map((event, index) => {
              const key = `${event.summary ?? event.title ?? "event"}-${index}`;
              return (
                <View key={key}>
                  {index > 0 && (
                    <View
                      style={{
                        height: 1,
                        backgroundColor: "rgba(255,255,255,0.07)",
                        marginHorizontal: 16,
                      }}
                    />
                  )}
                  <EventRow
                    event={event}
                    onPress={
                      onEventPress
                        ? () => onEventPress(event, index)
                        : undefined
                    }
                  />
                </View>
              );
            })}

            {overflow > 0 ? (
              <>
                <View
                  style={{
                    height: 1,
                    backgroundColor: "rgba(255,255,255,0.07)",
                  }}
                />
                <View className="px-4 py-2.5 items-center">
                  <Text className="text-muted text-xs">
                    +{overflow} more event{overflow !== 1 ? "s" : ""}
                  </Text>
                </View>
              </>
            ) : null}
          </ScrollView>
        )}
      </Card.Body>
    </Card>
  );
}
