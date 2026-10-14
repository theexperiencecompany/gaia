import { View } from "react-native";
import { Calendar03Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Types --------------------------------------------------------------------

export interface CalendarListFetchItem {
  name: string;
  id: string;
  description: string;
  backgroundColor?: string;
}

interface CalendarListFetchCardProps {
  data: CalendarListFetchItem[];
}

// Restored-history only: old conversations still carry this key. Read-only,
// no draft or add flows (those moved to HIL approvals by design).

export function CalendarListFetchCard({ data }: CalendarListFetchCardProps) {
  const items = (Array.isArray(data) ? data : [data]).filter(
    (calendar) => calendar.name,
  );

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Calendar03Icon}
        iconColor="#00bbff"
        title="Calendars"
        count={items.length}
      />
      {items.length === 0 ? (
        <Text className="text-muted text-sm">No calendars in this list.</Text>
      ) : (
        <View className="gap-2">
          {items.map((calendar) => (
            <View
              key={calendar.id || calendar.name}
              className="flex-row items-start gap-2 rounded-xl bg-zinc-900 p-3"
            >
              <View
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  marginTop: 5,
                  backgroundColor: calendar.backgroundColor || "#00bbff",
                }}
              />
              <View className="flex-1 min-w-0">
                <Text className="text-sm text-zinc-100" numberOfLines={1}>
                  {calendar.name}
                </Text>
                {calendar.description ? (
                  <Text className="text-xs text-muted mt-0.5" numberOfLines={2}>
                    {calendar.description}
                  </Text>
                ) : null}
              </View>
            </View>
          ))}
        </View>
      )}
    </ToolCardShell>
  );
}
