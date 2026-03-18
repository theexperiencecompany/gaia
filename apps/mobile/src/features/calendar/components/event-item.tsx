import { Card, Chip } from "heroui-native";
import { View } from "react-native";
import { AppIcon, Clock01Icon, Location01Icon } from "@/components/icons";
import type { CalendarEvent } from "../types/calendar-types";

interface EventItemProps {
  event: CalendarEvent;
}

function formatTimeRange(startTime: string, endTime: string): string {
  const start = new Date(startTime);
  const end = new Date(endTime);
  const fmt = (d: Date) =>
    d.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  return `${fmt(start)} – ${fmt(end)}`;
}

export function EventItem({ event }: EventItemProps) {
  return (
    <Card
      variant="secondary"
      animation="disable-all"
      className="mx-4 my-1 rounded-xl overflow-hidden border-l-[3px] border-l-primary"
    >
      <Card.Body className="px-3 py-3 gap-1.5">
        <View className="flex-row items-start justify-between gap-2">
          <Card.Title className="flex-1 text-[15px]" numberOfLines={2}>
            {event.title}
          </Card.Title>
          {!!event.calendar_name && (
            <Chip
              size="sm"
              variant="soft"
              color="accent"
              animation="disable-all"
            >
              <Chip.Label numberOfLines={1}>{event.calendar_name}</Chip.Label>
            </Chip>
          )}
        </View>

        <View className="flex-row items-center gap-1.5">
          <AppIcon icon={Clock01Icon} size={13} color="#8e8e93" />
          <Card.Description className="text-[13px]">
            {event.all_day
              ? "All day"
              : formatTimeRange(event.start_time, event.end_time)}
          </Card.Description>
        </View>

        {!!event.location && (
          <View className="flex-row items-center gap-1.5">
            <AppIcon icon={Location01Icon} size={13} color="#8e8e93" />
            <Card.Description className="text-[13px] flex-1" numberOfLines={1}>
              {event.location}
            </Card.Description>
          </View>
        )}
      </Card.Body>
    </Card>
  );
}
