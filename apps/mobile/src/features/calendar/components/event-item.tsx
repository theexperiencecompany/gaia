import { View } from "react-native";
import { AppIcon, Clock01Icon, Location01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
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
    <View
      style={{
        backgroundColor: "#18181b",
        borderRadius: 10,
        padding: 12,
        borderLeftWidth: 3,
        borderLeftColor: "#00bbff",
        marginHorizontal: 16,
        marginVertical: 4,
      }}
    >
      <Text
        style={{
          color: "#e8ebef",
          fontSize: 15,
          fontWeight: "600",
          marginBottom: 6,
        }}
        numberOfLines={2}
      >
        {event.title}
      </Text>

      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <AppIcon icon={Clock01Icon} size={13} color="#8e8e93" />
        <Text style={{ color: "#8e8e93", fontSize: 13 }}>
          {event.all_day
            ? "All day"
            : formatTimeRange(event.start_time, event.end_time)}
        </Text>
      </View>

      {!!event.location && (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            marginTop: 4,
          }}
        >
          <AppIcon icon={Location01Icon} size={13} color="#8e8e93" />
          <Text
            style={{ color: "#8e8e93", fontSize: 13, flex: 1 }}
            numberOfLines={1}
          >
            {event.location}
          </Text>
        </View>
      )}
    </View>
  );
}
