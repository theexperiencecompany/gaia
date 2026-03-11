import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Pressable, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Add01Icon,
  AppIcon,
  ArrowLeft01Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { todoApi } from "../api/todo-api";
import { useTodos } from "../hooks/use-todos";
import type { Todo, TodoCreate, TodoUpdate } from "../types/todo-types";
import { CreateTodoModal } from "./create-todo-modal";
import type { TodoDetailSheetRef } from "./todo-detail-sheet";
import { TodoDetailSheet } from "./todo-detail-sheet";
import { TodoFilters } from "./todo-filters";
import { TodoList } from "./todo-list";

export function TodoScreen() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const [showCreate, setShowCreate] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const detailSheetRef = useRef<TodoDetailSheetRef>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [activePriority, setActivePriority] = useState<string | null>(null);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 300);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [searchQuery]);

  const {
    todos,
    projects,
    counts,
    isLoading,
    isRefreshing,
    error,
    activeFilter,
    setActiveFilter,
    refetch,
    createTodo,
    updateTodo,
    toggleComplete,
    deleteTodo,
  } = useTodos({
    search: debouncedSearch || undefined,
    priority: activePriority || undefined,
  });

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  const handleCreated = async (data: TodoCreate) => {
    try {
      await createTodo(data);
      setShowCreate(false);
    } catch {
      // error is handled in the hook
    }
  };

  const handleEnterSelectionMode = useCallback((todo: Todo) => {
    setSelectionMode(true);
    setSelectedIds(new Set([todo.id]));
  }, []);

  const handleSelectTodo = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleCancelSelection = useCallback(() => {
    setSelectionMode(false);
    setSelectedIds(new Set());
  }, []);

  const handleBulkComplete = useCallback(async () => {
    if (selectedIds.size === 0) return;
    try {
      await todoApi.bulkComplete(Array.from(selectedIds));
      setSelectionMode(false);
      setSelectedIds(new Set());
      void refetch();
    } catch {
      Alert.alert("Error", "Failed to complete selected tasks.");
    }
  }, [selectedIds, refetch]);

  const handleBulkDelete = useCallback(() => {
    if (selectedIds.size === 0) return;
    Alert.alert(
      "Delete Tasks",
      `Are you sure you want to delete ${selectedIds.size} task${selectedIds.size === 1 ? "" : "s"}?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              await todoApi.bulkDelete(Array.from(selectedIds));
              setSelectionMode(false);
              setSelectedIds(new Set());
              void refetch();
            } catch {
              Alert.alert("Error", "Failed to delete selected tasks.");
            }
          },
        },
      ],
    );
  }, [selectedIds, refetch]);

  const handleTodoPress = useCallback((todo: Todo) => {
    detailSheetRef.current?.open(todo);
  }, []);

  const handleUpdate = useCallback(
    async (todoId: string, updates: TodoUpdate) => {
      await updateTodo(todoId, updates);
    },
    [updateTodo],
  );

  const handleAddSubtask = useCallback(
    async (todoId: string, title: string) => {
      await todoApi.addSubtask(todoId, title);
      void refetch();
    },
    [refetch],
  );

  const handleToggleSubtask = useCallback(
    async (todoId: string, subtaskId: string, completed: boolean) => {
      await todoApi.toggleSubtask(todoId, subtaskId, completed);
      void refetch();
    },
    [refetch],
  );

  const handleDeleteSubtask = useCallback(
    async (todoId: string, subtaskId: string) => {
      await todoApi.deleteSubtask(todoId, subtaskId);
      void refetch();
    },
    [refetch],
  );

  return (
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.07)",
          flexDirection: "row",
          alignItems: "center",
        }}
      >
        <Pressable
          onPress={() => router.back()}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
        </Pressable>

        <Text
          style={{
            marginLeft: spacing.md,
            fontSize: fontSize.lg,
            fontWeight: "600",
            color: "#f4f4f5",
            flex: 1,
          }}
        >
          Todos
        </Text>

        <Pressable
          onPress={() => setShowCreate(true)}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(22,193,255,0.15)",
          }}
        >
          <AppIcon icon={Add01Icon} size={18} color="#16c1ff" />
        </Pressable>
      </View>

      {/* Search bar */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 10,
          marginHorizontal: 16,
          marginTop: 12,
          marginBottom: 4,
          backgroundColor: "#18181b",
          borderRadius: 10,
          paddingHorizontal: 12,
          paddingVertical: 10,
          borderWidth: 1,
          borderColor: "#27272a",
        }}
      >
        <AppIcon icon={Search01Icon} size={16} color="#52525b" />
        <TextInput
          value={searchQuery}
          onChangeText={setSearchQuery}
          placeholder="Search todos..."
          placeholderTextColor="#52525b"
          style={{ flex: 1, fontSize: 15, color: "#f4f4f5" }}
          clearButtonMode="while-editing"
        />
      </View>

      {/* Filter tabs */}
      <TodoFilters
        activeFilter={activeFilter}
        onFilterChange={setActiveFilter}
        counts={counts}
        activePriority={activePriority}
        onPriorityFilter={setActivePriority}
      />

      {/* Error state */}
      {error ? (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: spacing.xl,
            gap: spacing.md,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#ef4444",
              textAlign: "center",
            }}
          >
            {error}
          </Text>
          <Pressable
            onPress={() => {
              void refetch();
            }}
            style={{
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
              backgroundColor: "rgba(22,193,255,0.1)",
            }}
          >
            <Text style={{ fontSize: fontSize.sm, color: "#16c1ff" }}>
              Try again
            </Text>
          </Pressable>
        </View>
      ) : (
        <TodoList
          todos={todos}
          projects={projects}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          onRefresh={() => {
            void refetch();
          }}
          onToggleComplete={toggleComplete}
          onTodoPress={selectionMode ? undefined : handleTodoPress}
          onDeleteTodo={
            selectionMode
              ? undefined
              : (id) => {
                  void deleteTodo(id);
                }
          }
          selectionMode={selectionMode}
          selectedIds={selectedIds}
          onEnterSelectionMode={handleEnterSelectionMode}
          onSelectTodo={handleSelectTodo}
        />
      )}

      {/* Bulk action bar */}
      {selectionMode && (
        <View
          style={{
            position: "absolute",
            bottom: insets.bottom + 16,
            left: 16,
            right: 16,
            flexDirection: "row",
            gap: 8,
            backgroundColor: "#1c1c1e",
            borderRadius: 16,
            padding: 12,
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.1)",
          }}
        >
          <Pressable
            onPress={() => {
              void handleBulkComplete();
            }}
            style={{
              flex: 1,
              alignItems: "center",
              justifyContent: "center",
              paddingVertical: 10,
              borderRadius: 10,
              backgroundColor: "rgba(22,193,255,0.12)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: "#16c1ff",
              }}
            >
              Complete ({selectedIds.size})
            </Text>
          </Pressable>
          <Pressable
            onPress={handleBulkDelete}
            style={{
              paddingHorizontal: spacing.md,
              paddingVertical: 10,
              borderRadius: 10,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(239,68,68,0.1)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: "#ef4444",
              }}
            >
              Delete
            </Text>
          </Pressable>
          <Pressable
            onPress={handleCancelSelection}
            style={{
              paddingHorizontal: spacing.md,
              paddingVertical: 10,
              borderRadius: 10,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(255,255,255,0.06)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "500",
                color: "#a1a1aa",
              }}
            >
              Cancel
            </Text>
          </Pressable>
        </View>
      )}

      <CreateTodoModal
        visible={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={handleCreated}
        projects={projects}
      />

      <TodoDetailSheet
        ref={detailSheetRef}
        projects={projects}
        onUpdate={handleUpdate}
        onAddSubtask={handleAddSubtask}
        onToggleSubtask={handleToggleSubtask}
        onDeleteSubtask={handleDeleteSubtask}
      />
    </View>
  );
}
