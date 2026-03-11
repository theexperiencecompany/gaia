import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Pressable, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Add01Icon,
  AppIcon,
  ArrowLeft01Icon,
  Cancel01Icon,
  CheckmarkSquare03Icon,
  Delete02Icon,
  Flag02Icon,
  Folder02Icon,
  Search01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { todoApi } from "../api/todo-api";
import { useProjects } from "../hooks/use-projects";
import { useTodos } from "../hooks/use-todos";
import type {
  Project,
  Todo,
  TodoCreate,
  TodoUpdate,
} from "../types/todo-types";
import { Priority } from "../types/todo-types";
import { CreateTodoModal } from "./create-todo-modal";
import type { ProjectListSheetRef } from "./project-list-sheet";
import { ProjectListSheet } from "./project-list-sheet";
import type { TodoDetailSheetRef } from "./todo-detail-sheet";
import { TodoDetailSheet } from "./todo-detail-sheet";
import { TodoFilters } from "./todo-filters";
import { TodoList } from "./todo-list";

const BULK_PRIORITY_OPTIONS: { key: Priority; label: string; emoji: string }[] =
  [
    { key: Priority.HIGH, label: "High", emoji: "🔴" },
    { key: Priority.MEDIUM, label: "Medium", emoji: "🟠" },
    { key: Priority.LOW, label: "Low", emoji: "🟡" },
    { key: Priority.NONE, label: "None", emoji: "⚪" },
  ];

type BulkAction = "priority" | "project" | null;

export function TodoScreen() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const [showCreate, setShowCreate] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeBulkAction, setActiveBulkAction] = useState<BulkAction>(null);
  const detailSheetRef = useRef<TodoDetailSheetRef>(null);
  const projectListSheetRef = useRef<ProjectListSheetRef>(null);
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

  const {
    projects: managedProjects,
    createProject,
    deleteProject,
    refetch: refetchProjects,
  } = useProjects();

  useFocusEffect(
    useCallback(() => {
      void refetchProjects();
    }, [refetchProjects]),
  );

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
    setActiveBulkAction(null);
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

  const handleSelectAll = useCallback(() => {
    setSelectedIds(new Set(todos.map((t) => t.id)));
  }, [todos]);

  const handleCancelSelection = useCallback(() => {
    setSelectionMode(false);
    setSelectedIds(new Set());
    setActiveBulkAction(null);
  }, []);

  const handleBulkComplete = useCallback(async () => {
    if (selectedIds.size === 0) return;
    try {
      await todoApi.bulkComplete(Array.from(selectedIds));
      setSelectionMode(false);
      setSelectedIds(new Set());
      setActiveBulkAction(null);
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
              setActiveBulkAction(null);
              void refetch();
            } catch {
              Alert.alert("Error", "Failed to delete selected tasks.");
            }
          },
        },
      ],
    );
  }, [selectedIds, refetch]);

  const handleBulkChangePriority = useCallback(
    async (priority: Priority) => {
      if (selectedIds.size === 0) return;
      try {
        await todoApi.bulkUpdatePriority(Array.from(selectedIds), priority);
        setSelectionMode(false);
        setSelectedIds(new Set());
        setActiveBulkAction(null);
        void refetch();
      } catch {
        Alert.alert("Error", "Failed to update priority for selected tasks.");
      }
    },
    [selectedIds, refetch],
  );

  const handleBulkMoveToProject = useCallback(
    async (projectId: string | null) => {
      if (selectedIds.size === 0) return;
      try {
        await todoApi.bulkMoveToProject(Array.from(selectedIds), projectId);
        setSelectionMode(false);
        setSelectedIds(new Set());
        setActiveBulkAction(null);
        void refetch();
      } catch {
        Alert.alert("Error", "Failed to move selected tasks.");
      }
    },
    [selectedIds, refetch],
  );

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
        {selectionMode ? (
          <>
            <Pressable
              onPress={handleCancelSelection}
              style={{
                width: 36,
                height: 36,
                borderRadius: 999,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: "rgba(255,255,255,0.05)",
              }}
            >
              <AppIcon icon={Cancel01Icon} size={18} color="#fff" />
            </Pressable>

            <Text
              style={{
                marginLeft: spacing.md,
                fontSize: fontSize.base,
                fontWeight: "600",
                color: "#f4f4f5",
                flex: 1,
              }}
            >
              {selectedIds.size} selected
            </Text>

            <Pressable
              onPress={handleSelectAll}
              style={{
                backgroundColor: "rgba(22,193,255,0.1)",
                borderRadius: 8,
                paddingHorizontal: spacing.md,
                paddingVertical: 6,
              }}
            >
              <Text
                style={{
                  color: "#16c1ff",
                  fontSize: fontSize.xs,
                  fontWeight: "500",
                }}
              >
                Select All
              </Text>
            </Pressable>
          </>
        ) : (
          <>
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
              onPress={() => projectListSheetRef.current?.open()}
              style={{
                width: 36,
                height: 36,
                borderRadius: 999,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: "rgba(255,255,255,0.06)",
                marginRight: spacing.sm,
              }}
            >
              <AppIcon icon={Folder02Icon} size={18} color="#a1a1aa" />
            </Pressable>

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
          </>
        )}
      </View>

      {/* Search bar */}
      {!selectionMode && (
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
      )}

      {/* Filter tabs */}
      {!selectionMode && (
        <TodoFilters
          activeFilter={activeFilter}
          onFilterChange={setActiveFilter}
          counts={counts}
          activePriority={activePriority}
          onPriorityFilter={setActivePriority}
        />
      )}

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

      {/* Bulk action toolbar */}
      {selectionMode && (
        <View
          style={{
            position: "absolute",
            bottom: insets.bottom + 16,
            left: 16,
            right: 16,
            backgroundColor: "#1c1c1e",
            borderRadius: 16,
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.1)",
            overflow: "hidden",
          }}
        >
          {/* Change Priority sub-panel */}
          {activeBulkAction === "priority" && (
            <View
              style={{
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm,
                borderBottomWidth: 1,
                borderBottomColor: "rgba(255,255,255,0.07)",
                gap: 6,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#8e8e93",
                  fontWeight: "600",
                  textTransform: "uppercase",
                  letterSpacing: 0.6,
                  marginBottom: 4,
                }}
              >
                Set priority
              </Text>
              <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                {BULK_PRIORITY_OPTIONS.map((opt) => (
                  <Pressable
                    key={opt.key}
                    onPress={() => void handleBulkChangePriority(opt.key)}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 5,
                      paddingHorizontal: 12,
                      paddingVertical: 7,
                      borderRadius: 10,
                      backgroundColor: "rgba(255,255,255,0.06)",
                    }}
                  >
                    <Text style={{ fontSize: 14 }}>{opt.emoji}</Text>
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: "#c5cad2",
                        fontWeight: "500",
                      }}
                    >
                      {opt.label}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          )}

          {/* Move to Project sub-panel */}
          {activeBulkAction === "project" && (
            <View
              style={{
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm,
                borderBottomWidth: 1,
                borderBottomColor: "rgba(255,255,255,0.07)",
                gap: 6,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "#8e8e93",
                  fontWeight: "600",
                  textTransform: "uppercase",
                  letterSpacing: 0.6,
                  marginBottom: 4,
                }}
              >
                Move to project
              </Text>
              <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                <Pressable
                  onPress={() => void handleBulkMoveToProject(null)}
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 5,
                    paddingHorizontal: 12,
                    paddingVertical: 7,
                    borderRadius: 10,
                    backgroundColor: "rgba(255,255,255,0.06)",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      color: "#c5cad2",
                      fontWeight: "500",
                    }}
                  >
                    No Project
                  </Text>
                </Pressable>
                {managedProjects.map((project: Project) => (
                  <Pressable
                    key={project.id}
                    onPress={() => void handleBulkMoveToProject(project.id)}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 5,
                      paddingHorizontal: 12,
                      paddingVertical: 7,
                      borderRadius: 10,
                      backgroundColor: project.color
                        ? `${project.color}18`
                        : "rgba(255,255,255,0.06)",
                    }}
                  >
                    <View
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 4,
                        backgroundColor: project.color ?? "#71717a",
                      }}
                    />
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: project.color ?? "#c5cad2",
                        fontWeight: "500",
                      }}
                    >
                      {project.name}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          )}

          {/* Main toolbar actions */}
          <View
            style={{
              flexDirection: "row",
              gap: 8,
              padding: 12,
            }}
          >
            {/* Complete */}
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
                gap: 3,
              }}
            >
              <AppIcon icon={Tick02Icon} size={16} color="#16c1ff" />
              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  fontWeight: "600",
                  color: "#16c1ff",
                }}
              >
                Done
              </Text>
            </Pressable>

            {/* Change Priority */}
            <Pressable
              onPress={() =>
                setActiveBulkAction((prev) =>
                  prev === "priority" ? null : "priority",
                )
              }
              style={{
                flex: 1,
                alignItems: "center",
                justifyContent: "center",
                paddingVertical: 10,
                borderRadius: 10,
                backgroundColor:
                  activeBulkAction === "priority"
                    ? "rgba(234,179,8,0.18)"
                    : "rgba(234,179,8,0.09)",
                gap: 3,
              }}
            >
              <AppIcon
                icon={Flag02Icon}
                size={16}
                color={activeBulkAction === "priority" ? "#eab308" : "#a1a1aa"}
              />
              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  fontWeight: "600",
                  color:
                    activeBulkAction === "priority" ? "#eab308" : "#a1a1aa",
                }}
              >
                Priority
              </Text>
            </Pressable>

            {/* Move to Project */}
            <Pressable
              onPress={() =>
                setActiveBulkAction((prev) =>
                  prev === "project" ? null : "project",
                )
              }
              style={{
                flex: 1,
                alignItems: "center",
                justifyContent: "center",
                paddingVertical: 10,
                borderRadius: 10,
                backgroundColor:
                  activeBulkAction === "project"
                    ? "rgba(99,102,241,0.2)"
                    : "rgba(99,102,241,0.09)",
                gap: 3,
              }}
            >
              <AppIcon
                icon={CheckmarkSquare03Icon}
                size={16}
                color={activeBulkAction === "project" ? "#818cf8" : "#a1a1aa"}
              />
              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  fontWeight: "600",
                  color: activeBulkAction === "project" ? "#818cf8" : "#a1a1aa",
                }}
              >
                Project
              </Text>
            </Pressable>

            {/* Delete */}
            <Pressable
              onPress={handleBulkDelete}
              style={{
                flex: 1,
                alignItems: "center",
                justifyContent: "center",
                paddingVertical: 10,
                borderRadius: 10,
                backgroundColor: "rgba(239,68,68,0.1)",
                gap: 3,
              }}
            >
              <AppIcon icon={Delete02Icon} size={16} color="#ef4444" />
              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  fontWeight: "600",
                  color: "#ef4444",
                }}
              >
                Delete
              </Text>
            </Pressable>
          </View>
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

      <ProjectListSheet
        ref={projectListSheetRef}
        projects={managedProjects}
        onCreateProject={async (data) => {
          await createProject(data);
        }}
        onDeleteProject={async (id) => {
          await deleteProject(id);
        }}
      />
    </View>
  );
}
