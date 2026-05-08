import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Add01Icon,
  AppIcon,
  ArrowDown02Icon,
  Cancel01Icon,
  Folder02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { selectionHaptic } from "@/lib/haptics";
import { AppSearchInput } from "@/shared/components/ui/app-search-input";
import { BackButton } from "@/shared/components/ui/back-button";
import { TODO_FILTER_DESCRIPTORS } from "../../constants";
import type { FilterTab, SortOption, TodoCounts } from "../../types/todo-types";

interface TodoListHeaderProps {
  activeFilter: FilterTab;
  onFilterChange: (filter: FilterTab) => void;
  counts: TodoCounts | null;
  searchValue: string;
  onSearchChange: (value: string) => void;
  onAddTodo: () => void;
  onOpenProjects: () => void;
  activeSort: SortOption | null;
  onOpenSort: () => void;
  onClearSort: () => void;
}

/**
 * Sticky list header — title row + search + filter chips + sort affordance.
 * Used by `TodoListScreen`. The multi-select header morph is rendered by
 * `TodoBulkActionBar` instead.
 */
export function TodoListHeader({
  activeFilter,
  onFilterChange,
  counts,
  searchValue,
  onSearchChange,
  onAddTodo,
  onOpenProjects,
  activeSort,
  onOpenSort,
  onClearSort,
}: TodoListHeaderProps) {
  const insets = useSafeAreaInsets();

  return (
    <View
      style={{
        backgroundColor: "#0a0a0a",
        paddingTop: insets.top + 6,
        paddingBottom: 8,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingHorizontal: 16,
          paddingBottom: 10,
        }}
      >
        <BackButton />
        <Text
          style={{
            fontSize: 22,
            fontWeight: "600",
            color: "#fafafa",
            flex: 1,
            marginLeft: 8,
          }}
        >
          Todos
        </Text>
        <Pressable
          onPress={onOpenProjects}
          hitSlop={8}
          accessibilityLabel="Browse projects"
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(63,63,70,0.40)",
          }}
        >
          <AppIcon icon={Folder02Icon} size={18} color="#a1a1aa" />
        </Pressable>
        <Pressable
          onPress={onAddTodo}
          hitSlop={8}
          accessibilityLabel="Add todo"
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "#00bbff",
          }}
        >
          <AppIcon icon={Add01Icon} size={18} color="#0a0a0a" />
        </Pressable>
      </View>

      <View style={{ paddingHorizontal: 16, marginBottom: 8 }}>
        <AppSearchInput
          value={searchValue}
          onChangeText={onSearchChange}
          placeholder="Search todos"
        />
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{
          paddingHorizontal: 16,
          gap: 8,
          alignItems: "center",
        }}
      >
        {TODO_FILTER_DESCRIPTORS.map((descriptor) => {
          const isActive = descriptor.key === activeFilter;
          const count = descriptor.countKey
            ? (counts?.[descriptor.countKey] ?? null)
            : null;
          return (
            <Pressable
              key={descriptor.key}
              onPress={() => {
                selectionHaptic();
                onFilterChange(descriptor.key);
              }}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                paddingHorizontal: 12,
                paddingVertical: 7,
                borderRadius: 999,
                backgroundColor: isActive ? "#00bbff" : "rgba(63,63,70,0.40)",
              }}
            >
              <Text
                style={{
                  fontSize: 13,
                  fontWeight: "600",
                  color: isActive ? "#0a0a0a" : "#e4e4e7",
                }}
              >
                {descriptor.label}
              </Text>
              {count !== null && count > 0 && (
                <View
                  style={{
                    backgroundColor: isActive
                      ? "rgba(10,10,10,0.18)"
                      : "rgba(63,63,70,0.60)",
                    borderRadius: 999,
                    paddingHorizontal: 6,
                    paddingVertical: 1,
                    minWidth: 20,
                    alignItems: "center",
                  }}
                >
                  <Text
                    style={{
                      fontSize: 11,
                      fontWeight: "600",
                      color: isActive ? "#0a0a0a" : "#a1a1aa",
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

      <View
        style={{
          flexDirection: "row",
          justifyContent: "flex-end",
          alignItems: "center",
          paddingHorizontal: 16,
          paddingTop: 8,
          gap: 6,
        }}
      >
        {activeSort ? (
          <Pressable
            onPress={() => {
              selectionHaptic();
              onClearSort();
            }}
            hitSlop={6}
            accessibilityLabel="Clear sort"
            style={{
              width: 22,
              height: 22,
              borderRadius: 11,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(63,63,70,0.40)",
            }}
          >
            <AppIcon icon={Cancel01Icon} size={11} color="#a1a1aa" />
          </Pressable>
        ) : null}
        <Pressable
          onPress={() => {
            selectionHaptic();
            onOpenSort();
          }}
          hitSlop={6}
          accessibilityLabel="Open sort options"
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
            paddingHorizontal: 8,
            paddingVertical: 4,
          }}
        >
          <AppIcon icon={ArrowDown02Icon} size={12} color="#a1a1aa" />
          <Text style={{ fontSize: 12, color: "#a1a1aa", fontWeight: "500" }}>
            {activeSort ? activeSort.label : "Sort"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}
