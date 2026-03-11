import { Button, Card, Chip, PressableFeedback } from "heroui-native";
import { View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  CheckmarkCircle01Icon,
  Clock01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Types --------------------------------------------------------------------

export interface CalendarOption {
  title?: string;
  start?: string;
  end?: string;
  location?: string;
  description?: string;
  attendees?: Array<{ email?: string; displayName?: string }>;
  background_color?: string;
  calendar_name?: string;
}

interface CalendarOptionsCardProps {
  data: CalendarOption[];
  onSelect?: (index: number) => void;
  selectedIndex?: number;
}

// -- Helpers ------------------------------------------------------------------

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

// -- Option row ---------------------------------------------------------------

interface OptionRowProps {
  event: CalendarOption;
  index: number;
  isSelected: boolean;
  onSelect?: (index: number) => void;
}

function OptionRow({ event, index, isSelected, onSelect }: OptionRowProps) {
  const timeRange = formatTimeRange(event.start, event.end);
  const attendeeCount = event.attendees?.length ?? 0;
  const eventColor = event.background_color ?? "#00bbff";

  const handlePress = () => onSelect?.(index);

  return (
    <PressableFeedback onPress={handlePress}>
      <View
        className="py-3 px-4"
        style={isSelected ? { backgroundColor: `${eventColor}10` } : undefined}
      >
        <View className="flex-row items-start gap-3">
          {/* Icon */}
          <View
            className="w-9 h-9 rounded-xl items-center justify-center flex-shrink-0"
            style={{
              backgroundColor: isSelected
                ? `${eventColor}25`
                : "rgba(255,255,255,0.06)",
            }}
          >
            <AppIcon
              icon={isSelected ? CheckmarkCircle01Icon : Calendar03Icon}
              size={18}
              color={isSelected ? eventColor : "#8e8e93"}
            />
          </View>

          {/* Info */}
          <View className="flex-1 min-w-0">
            <Text
              className="text-sm font-medium text-foreground mb-0.5"
              numberOfLines={1}
            >
              {event.title ?? "Untitled Event"}
            </Text>

            {timeRange ? (
              <View className="flex-row items-center gap-1 mb-0.5">
                <AppIcon icon={Clock01Icon} size={11} color="#8e8e93" />
                <Text className="text-muted text-xs">{timeRange}</Text>
              </View>
            ) : null}

            {event.location ? (
              <Text className="text-muted text-xs mb-0.5" numberOfLines={1}>
                {event.location}
              </Text>
            ) : null}

            {event.description ? (
              <Text
                className="text-muted text-xs mb-1 leading-4"
                numberOfLines={2}
              >
                {event.description}
              </Text>
            ) : null}

            {attendeeCount > 0 ? (
              <Text className="text-muted text-xs mb-1.5">
                {attendeeCount} attendee{attendeeCount !== 1 ? "s" : ""}
              </Text>
            ) : null}

            {event.calendar_name ? (
              <Chip
                size="sm"
                variant="soft"
                className="self-start mb-1"
                animation="disable-all"
              >
                <Chip.Label>{event.calendar_name}</Chip.Label>
              </Chip>
            ) : null}
          </View>

          {/* Selected badge */}
          {isSelected ? (
            <Chip
              size="sm"
              variant="soft"
              className="flex-shrink-0"
              animation="disable-all"
            >
              <Chip.Label>Selected</Chip.Label>
            </Chip>
          ) : null}
        </View>

        {/* Select button (only shown when not selected) */}
        {!isSelected ? (
          <View className="mt-2 ml-12">
            <Button
              variant="secondary"
              size="sm"
              className="self-start rounded-xl"
              onPress={handlePress}
            >
              <AppIcon icon={Calendar03Icon} size={12} color="#00bbff" />
              <Button.Label>Select this time</Button.Label>
            </Button>
          </View>
        ) : null}
      </View>
    </PressableFeedback>
  );
}

// -- Calendar options card ----------------------------------------------------

export function CalendarOptionsCard({
  data,
  onSelect,
  selectedIndex,
}: CalendarOptionsCardProps) {
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
            <Card.Title>Proposed Times</Card.Title>
            <Card.Description>Choose a time slot to schedule</Card.Description>
          </View>
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
          >
            <Chip.Label>
              {data.length} option{data.length !== 1 ? "s" : ""}
            </Chip.Label>
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
            <Text className="text-muted text-sm">No options available</Text>
          </View>
        ) : (
          data.map((event, index) => {
            const key = `${event.title ?? "option"}-${index}`;
            const isSelected = selectedIndex === index;
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
                <OptionRow
                  event={event}
                  index={index}
                  isSelected={isSelected}
                  onSelect={onSelect}
                />
              </View>
            );
          })
        )}
      </Card.Body>
    </Card>
  );
}
