import { View } from "react-native";
import { Calendar03Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Types --------------------------------------------------------------------

export interface CalendarListFetchItem {
  id: string;
  name: string;
  description?: string;
  backgroundColor?: string;
}

interface CalendarListFetchCardProps {
  data: CalendarListFetchItem[];
}

// -- Calendar list fetch card -------------------------------------------------

export function CalendarListFetchCard({ data }: CalendarListFetchCardProps) {
  const sorted = [...data].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Calendar03Icon}
        title="Calendars"
        count={data.length}
      />

      {sorted.length === 0 ? (
        <Text className="text-zinc-500 text-sm">No calendars found</Text>
      ) : (
        <View className="gap-1.5">
          {sorted.map((calendar) => {
            const dot = calendar.backgroundColor ?? "#00bbff";
            return (
              <View
                key={calendar.id}
                className="flex-row items-center gap-3 rounded-xl bg-zinc-900 p-3"
              >
                {/* Color dot */}
                <View
                  className="w-3 h-3 rounded-full flex-shrink-0"
                  style={{ backgroundColor: dot }}
                />
                <View className="flex-1 min-w-0">
                  <Text
                    className="text-zinc-100 text-sm font-medium"
                    numberOfLines={1}
                  >
                    {calendar.name}
                  </Text>
                  {calendar.description ? (
                    <Text
                      className="text-zinc-500 text-xs mt-0.5"
                      numberOfLines={1}
                    >
                      {calendar.description}
                    </Text>
                  ) : null}
                </View>
              </View>
            );
          })}
        </View>
      )}
    </ToolCardShell>
  );
}
