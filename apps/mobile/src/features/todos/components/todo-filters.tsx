import { useRouter } from "expo-router";
import { useRef } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { AppIcon, ArrowRight01Icon, Flag02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { FilterTab, TodoCounts } from "../types/todo-types";

interface TodoFiltersProps {
  activeFilter: FilterTab;
  onFilterChange: (filter: FilterTab) => void;
  counts: TodoCounts | null;
  activePriority?: string | null;
  onPriorityFilter: (priority: string | null) => void;
}

const PRIORITY_OPTIONS = [
  { key: "high", label: "High", color: "#ef4444" },
  { key: "medium", label: "Medium", color: "#f97316" },
  { key: "low", label: "Low", color: "#eab308" },
] as const;

const PRIORITY_NAV_OPTIONS = [
  { key: "high", label: "Urgent / High", emoji: "🔴", color: "#ef4444" },
  { key: "medium", label: "Medium", emoji: "🟠", color: "#f97316" },
  { key: "low", label: "Low", emoji: "🟡", color: "#eab308" },
] as const;

const FILTERS: {
  key: FilterTab;
  label: string;
  countKey?: keyof TodoCounts;
}[] = [
  { key: "all", label: "All", countKey: "inbox" },
  { key: "today", label: "Today", countKey: "today" },
  { key: "upcoming", label: "Upcoming", countKey: "upcoming" },
  { key: "completed", label: "Completed", countKey: "completed" },
];

export function TodoFilters({
  activeFilter,
  onFilterChange,
  counts,
  activePriority,
  onPriorityFilter,
}: TodoFiltersProps) {
  const { spacing, fontSize } = useResponsive();
  const scrollRef = useRef<ScrollView>(null);
  const router = useRouter();

  return (
    <View
      style={{
        paddingVertical: spacing.sm,
        borderBottomWidth: 1,
        borderBottomColor: "rgba(255,255,255,0.06)",
      }}
    >
      {/* Tab filters row */}
      <ScrollView
        ref={scrollRef}
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{
          paddingHorizontal: spacing.md,
          gap: spacing.sm,
          alignItems: "center",
        }}
      >
        {FILTERS.map((filter) => {
          const isActive = activeFilter === filter.key;
          const count =
            filter.countKey && counts ? counts[filter.countKey] : null;

          return (
            <Pressable
              key={filter.key}
              onPress={() => onFilterChange(filter.key)}
              style={{
                flexDirection: "row",
                alignItems: "center",
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.xs + 2,
                borderRadius: 999,
                backgroundColor: isActive
                  ? "rgba(22,193,255,0.15)"
                  : "rgba(255,255,255,0.05)",
                borderWidth: 1,
                borderColor: isActive ? "rgba(22,193,255,0.3)" : "transparent",
                gap: 5,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  fontWeight: isActive ? "600" : "400",
                  color: isActive ? "#9fe6ff" : "#8e8e93",
                }}
              >
                {filter.label}
              </Text>
              {count != null && count > 0 && (
                <View
                  style={{
                    backgroundColor: isActive
                      ? "rgba(22,193,255,0.25)"
                      : "rgba(255,255,255,0.08)",
                    borderRadius: 999,
                    paddingHorizontal: 6,
                    paddingVertical: 1,
                    minWidth: 18,
                    alignItems: "center",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs - 1,
                      fontWeight: "600",
                      color: isActive ? "#9fe6ff" : "#71717a",
                    }}
                  >
                    {count}
                  </Text>
                </View>
              )}
            </Pressable>
          );
        })}
      </ScrollView>

      {/* Inline priority filter chips */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{
          paddingHorizontal: 16,
          gap: 8,
          paddingVertical: 4,
        }}
      >
        {PRIORITY_OPTIONS.map((opt) => {
          const isActive = activePriority === opt.key;
          return (
            <Pressable
              key={opt.key}
              onPress={() => onPriorityFilter(isActive ? null : opt.key)}
              style={{
                paddingHorizontal: 12,
                paddingVertical: 6,
                borderRadius: 20,
                backgroundColor: isActive ? `${opt.color}20` : "#18181b",
                borderWidth: 1,
                borderColor: isActive ? opt.color : "#27272a",
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
              }}
            >
              <View
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: opt.color,
                }}
              />
              <Text
                style={{
                  fontSize: 13,
                  color: isActive ? opt.color : "#a1a1aa",
                }}
              >
                {opt.label}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>

      {/* Priority navigation section — tapping opens dedicated priority view */}
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingTop: spacing.xs,
          gap: 2,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            paddingVertical: spacing.xs,
          }}
        >
          <AppIcon icon={Flag02Icon} size={12} color="#8e8e93" />
          <Text
            style={{
              fontSize: fontSize.xs,
              fontWeight: "600",
              letterSpacing: 0.7,
              textTransform: "uppercase",
              color: "#636366",
            }}
          >
            Priority Views
          </Text>
        </View>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: 6, paddingBottom: spacing.xs }}
        >
          {PRIORITY_NAV_OPTIONS.map((opt) => (
            <Pressable
              key={opt.key}
              onPress={() =>
                router.push(`/(app)/(tabs)/todos/priority/${opt.key}` as never)
              }
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                paddingHorizontal: 12,
                paddingVertical: 6,
                borderRadius: 10,
                backgroundColor: "#18181b",
                borderWidth: 1,
                borderColor: "#27272a",
              }}
            >
              <Text style={{ fontSize: 13 }}>{opt.emoji}</Text>
              <Text style={{ fontSize: fontSize.xs, color: "#c5cad2" }}>
                {opt.label}
              </Text>
              <AppIcon
                icon={ArrowRight01Icon}
                size={12}
                color="rgba(255,255,255,0.2)"
              />
            </Pressable>
          ))}
        </ScrollView>
      </View>
    </View>
  );
}
