import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  LayoutAnimation,
  Platform,
  Pressable,
  UIManager,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import { useSidebar } from "@/features/chat/hooks/sidebar-context";
import { useConfirmDialog } from "@/shared/components/ui/app-confirm-dialog";
import { todoApi } from "../../api/todo-api";
import { useProjects } from "../../hooks/use-projects";
import { useTodos } from "../../hooks/use-todos";
import type {
  Priority,
  SortOption,
  Todo,
  TodoCreate,
  TodoUpdate,
} from "../../types/todo-types";
import {
  TodoCreateSheet,
  type TodoCreateSheetRef,
} from "../create/todo-create-sheet";
import type { TodoDetailSheetRef } from "../detail/todo-detail-sheet";
import { TodoDetailSheet } from "../detail/todo-detail-sheet";
import {
  SnoozeActionSheet,
  type SnoozeActionSheetRef,
} from "../sheets/snooze-action-sheet";
import {
  TodoSearchSheet,
  type TodoSearchSheetRef,
} from "../sheets/todo-search-sheet";
import { SortPickerSheet, type SortPickerSheetRef } from "../sort-picker-sheet";
import { TodoBulkActionBar } from "./todo-bulk-action-bar";
import { TodoListHeader } from "./todo-list-header";
import { TodoSectionList } from "./todo-section-list";
import { TodoUndoToast, type UndoState } from "./todo-undo-toast";

if (
  Platform.OS === "android" &&
  UIManager.setLayoutAnimationEnabledExperimental
) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

const UNDO_HOLD_MS = 5000;

export function TodoListScreen() {
  const confirm = useConfirmDialog();
  const insets = useSafeAreaInsets();
  const { toggleSidebar } = useSidebar();
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeSort, setActiveSort] = useState<SortOption | null>(null);
  const [undo, setUndo] = useState<UndoState | null>(null);
  // Hold the currently snoozed todo so the snooze sheet can apply to it
  // when invoked from a row swipe; null when invoked from bulk bar.
  const snoozeTargetRef = useRef<Todo | null>(null);
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const detailSheetRef = useRef<TodoDetailSheetRef>(null);
  const createSheetRef = useRef<TodoCreateSheetRef>(null);
  const snoozeSheetRef = useRef<SnoozeActionSheetRef>(null);
  const sortSheetRef = useRef<SortPickerSheetRef>(null);
  const searchSheetRef = useRef<TodoSearchSheetRef>(null);

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
  } = useTodos();

  const { projects: managedProjects, refetch: refetchProjects } = useProjects();

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

  const clearUndoTimer = useCallback(() => {
    if (undoTimerRef.current) {
      clearTimeout(undoTimerRef.current);
      undoTimerRef.current = null;
    }
  }, []);

  const showUndo = useCallback(
    (state: UndoState) => {
      clearUndoTimer();
      setUndo(state);
      undoTimerRef.current = setTimeout(() => {
        setUndo(null);
        undoTimerRef.current = null;
      }, UNDO_HOLD_MS);
    },
    [clearUndoTimer],
  );

  const dismissUndo = useCallback(() => {
    clearUndoTimer();
    setUndo(null);
  }, [clearUndoTimer]);

  // Clean up the undo timer on unmount.
  useEffect(() => () => clearUndoTimer(), [clearUndoTimer]);

  const enterSelection = useCallback((todo: Todo) => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setSelectionMode(true);
    setSelectedIds(new Set([todo.id]));
  }, []);

  const cancelSelection = useCallback(() => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setSelectionMode(false);
    setSelectedIds(new Set());
  }, []);

  const handleSelectTodo = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    setSelectedIds(new Set(todos.map((t) => t.id)));
  }, [todos]);

  const handleBulkComplete = useCallback(async () => {
    if (selectedIds.size === 0) return;
    try {
      await todoApi.bulkCompleteTodos(Array.from(selectedIds));
      cancelSelection();
      void refetch();
    } catch {
      Alert.alert("Error", "Failed to complete selected todos.");
    }
  }, [selectedIds, refetch, cancelSelection]);

  const handleBulkDelete = useCallback(async () => {
    if (selectedIds.size === 0) return;
    const n = selectedIds.size;
    const ok = await confirm({
      title: "Delete todos",
      message: `Delete ${n} todo${n === 1 ? "" : "s"}? This cannot be undone.`,
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    try {
      await todoApi.bulkDeleteTodos(Array.from(selectedIds));
      cancelSelection();
      void refetch();
    } catch {
      Alert.alert("Error", "Failed to delete selected todos.");
    }
  }, [confirm, selectedIds, refetch, cancelSelection]);

  const handleBulkPriority = useCallback(
    async (priority: Priority) => {
      if (selectedIds.size === 0) return;
      try {
        await todoApi.bulkUpdatePriority(Array.from(selectedIds), priority);
        cancelSelection();
        void refetch();
      } catch {
        Alert.alert("Error", "Failed to update priority.");
      }
    },
    [selectedIds, refetch, cancelSelection],
  );

  const handleBulkMove = useCallback(
    async (projectId: string | null) => {
      if (selectedIds.size === 0) return;
      try {
        await todoApi.bulkMoveToProject(Array.from(selectedIds), projectId);
        cancelSelection();
        void refetch();
      } catch {
        Alert.alert("Error", "Failed to move selected todos.");
      }
    },
    [selectedIds, refetch, cancelSelection],
  );

  const handleSnoozePicked = useCallback(
    async (iso: string) => {
      try {
        if (snoozeTargetRef.current) {
          await updateTodo(snoozeTargetRef.current.id, { due_date: iso });
          snoozeTargetRef.current = null;
        } else if (selectedIds.size > 0) {
          await Promise.all(
            Array.from(selectedIds).map((id) =>
              todoApi.updateTodo(id, { due_date: iso }),
            ),
          );
          cancelSelection();
          void refetch();
        }
      } catch {
        Alert.alert("Error", "Failed to snooze.");
      }
    },
    [updateTodo, selectedIds, refetch, cancelSelection],
  );

  const openSnooze = useCallback((todo: Todo | null) => {
    snoozeTargetRef.current = todo;
    snoozeSheetRef.current?.open();
  }, []);

  const handleTodoPress = useCallback((todo: Todo) => {
    detailSheetRef.current?.open(todo);
  }, []);

  const handleTodoDelete = useCallback(
    async (todo: Todo) => {
      const ok = await confirm({
        title: "Delete todo",
        message: `Delete "${todo.title}"?`,
        confirmLabel: "Delete",
        destructive: true,
      });
      if (!ok) return;
      void deleteTodo(todo.id);
      showUndo({
        kind: "delete",
        message: `Deleted "${todo.title}"`,
        onUndo: async () => {
          try {
            await todoApi.createTodo({
              title: todo.title,
              description: todo.description,
              labels: todo.labels,
              due_date: todo.due_date,
              due_date_timezone: todo.due_date_timezone,
              priority: todo.priority,
              project_id: todo.project_id,
            });
            void refetch();
          } catch {
            // ignore — best-effort recreate
          }
        },
      });
    },
    [confirm, deleteTodo, showUndo, refetch],
  );

  const handleTodoMenu = useCallback(
    (todo: Todo) => {
      // Android fallback — same actions, just routed through Alert.
      Alert.alert(todo.title, undefined, [
        { text: "Edit", onPress: () => handleTodoPress(todo) },
        { text: "Snooze", onPress: () => openSnooze(todo) },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => handleTodoDelete(todo),
        },
        { text: "Cancel", style: "cancel" },
      ]);
    },
    [handleTodoPress, handleTodoDelete, openSnooze],
  );

  const handleCreated = useCallback(
    async (data: TodoCreate) => {
      try {
        await createTodo(data);
      } catch {
        // handled in hook
      }
    },
    [createTodo],
  );

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
    <View style={{ flex: 1, backgroundColor: "#111111" }}>
      {!selectionMode ? (
        <TodoListHeader
          activeFilter={activeFilter}
          onFilterChange={setActiveFilter}
          counts={counts}
          onAddTodo={() => createSheetRef.current?.open()}
          onOpenDrawer={toggleSidebar}
          onOpenSearch={() => searchSheetRef.current?.open()}
          activeSort={activeSort}
          onOpenSort={() => sortSheetRef.current?.open()}
          onClearSort={() => setActiveSort(null)}
        />
      ) : (
        <View style={{ paddingTop: insets.top, backgroundColor: "#111111" }} />
      )}

      {error ? (
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: 32,
            gap: 12,
          }}
        >
          <Text style={{ fontSize: 14, color: "#fca5a5", textAlign: "center" }}>
            {error}
          </Text>
          <Pressable
            onPress={() => void refetch()}
            style={{
              borderRadius: 10,
              paddingHorizontal: 14,
              paddingVertical: 10,
              backgroundColor: "rgba(0,187,255,0.15)",
            }}
          >
            <Text style={{ fontSize: 13, color: "#00bbff", fontWeight: "600" }}>
              Try again
            </Text>
          </Pressable>
        </View>
      ) : (
        <TodoSectionList
          todos={todos}
          projects={projects}
          filter={activeFilter}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          isSearchEmpty={false}
          onRefresh={() => void refetch()}
          onToggleComplete={toggleComplete}
          onTodoPress={handleTodoPress}
          onTodoDelete={handleTodoDelete}
          onTodoSnooze={openSnooze}
          onTodoLongPress={enterSelection}
          onTodoOpenMenu={handleTodoMenu}
          onAddTodo={() => createSheetRef.current?.open()}
          selectionMode={selectionMode}
          selectedIds={selectedIds}
          onSelectTodo={handleSelectTodo}
          activeSort={activeSort}
        />
      )}

      {selectionMode && (
        <TodoBulkActionBar
          selectedCount={selectedIds.size}
          onCancel={cancelSelection}
          onSelectAll={handleSelectAll}
          onComplete={handleBulkComplete}
          onChangePriority={handleBulkPriority}
          onMoveToProject={handleBulkMove}
          onDelete={handleBulkDelete}
          onSnooze={() => openSnooze(null)}
          projects={managedProjects}
        />
      )}

      <TodoCreateSheet
        ref={createSheetRef}
        projects={projects}
        onCreated={handleCreated}
      />

      <TodoDetailSheet
        ref={detailSheetRef}
        projects={projects}
        onUpdate={handleUpdate}
        onDelete={handleTodoDelete}
        onAddSubtask={handleAddSubtask}
        onToggleSubtask={handleToggleSubtask}
        onDeleteSubtask={handleDeleteSubtask}
      />

      <SortPickerSheet
        ref={sortSheetRef}
        activeSort={activeSort}
        onSelect={setActiveSort}
        onClear={() => setActiveSort(null)}
      />

      <SnoozeActionSheet ref={snoozeSheetRef} onPick={handleSnoozePicked} />

      <TodoSearchSheet
        ref={searchSheetRef}
        onSelect={(todo) => detailSheetRef.current?.open(todo)}
      />

      <TodoUndoToast undo={undo} onDismiss={dismissUndo} />
    </View>
  );
}
