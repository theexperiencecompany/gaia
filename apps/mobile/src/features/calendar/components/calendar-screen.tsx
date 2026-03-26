import { Divider, SkeletonGroup, Surface } from "heroui-native";
import { useCallback, useState } from "react";
import { RefreshControl, SectionList, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import { useUpcomingEvents } from "../hooks/use-calendar";
import type { CalendarEvent, CalendarSection } from "../types/calendar-types";
import { EventItem } from "./event-item";

function groupByDate(events: CalendarEvent[]): CalendarSection[] {
  const groups: Record<string, CalendarEvent[]> = {};
  for (const e of events) {
    const key = new Date(e.start_time).toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
    groups[key] ??= [];
    groups[key].push(e);
  }
  return Object.entries(groups).map(([title, data]) => ({ title, data }));
}

function LoadingSkeleton() {
  return (
    <SkeletonGroup isLoading className="pt-2 gap-0">
      {[0, 1, 2, 3, 4].map((i) => (
        <SkeletonGroup.Item key={i} className="mx-4 my-1 h-[70px] rounded-xl" />
      ))}
    </SkeletonGroup>
  );
}

export function CalendarScreen() {
  const { data: events, isLoading, refetch } = useUpcomingEvents();
  const [isRefreshing, setIsRefreshing] = useState(false);

  const sections: CalendarSection[] = events ? groupByDate(events) : [];

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await refetch();
    } finally {
      setIsRefreshing(false);
    }
  }, [refetch]);

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: "#0f1011" }}
      edges={["top"]}
    >
      <Surface variant="transparent" className="px-4 pt-4 pb-3">
        <Text
          style={{
            fontSize: 28,
            fontWeight: "700",
            color: "#e8ebef",
          }}
        >
          Calendar
        </Text>
      </Surface>

      {isLoading ? (
        <LoadingSkeleton />
      ) : sections.length === 0 ? (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: 32,
          }}
        >
          <Text
            style={{
              color: "#8e8e93",
              fontSize: 15,
              textAlign: "center",
              lineHeight: 22,
            }}
          >
            No upcoming events. Connect your calendar in Integrations.
          </Text>
        </View>
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={(item) => item.id}
          renderItem={({ item, index }) => (
            <>
              {index > 0 && <Divider className="mx-4 my-0.5" />}
              <EventItem event={item} />
            </>
          )}
          renderSectionHeader={({ section }) => (
            <Text
              style={{
                fontSize: 11,
                fontWeight: "600",
                letterSpacing: 0.8,
                textTransform: "uppercase",
                color: "#8e8e93",
                paddingHorizontal: 16,
                paddingTop: 16,
                paddingBottom: 4,
              }}
            >
              {section.title}
            </Text>
          )}
          contentContainerStyle={{ paddingBottom: 32 }}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={handleRefresh}
              tintColor="#00bbff"
            />
          }
          stickySectionHeadersEnabled={false}
        />
      )}
    </SafeAreaView>
  );
}
