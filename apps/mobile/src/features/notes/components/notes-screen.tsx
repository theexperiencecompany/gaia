import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useRef } from "react";
import { Pressable, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Add01Icon,
  AppIcon,
  ArrowLeft01Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Note } from "../api/notes-api";
import { useNotes } from "../hooks/use-notes";
import type { NoteEditorSheetRef } from "./note-editor-sheet";
import { NoteEditorSheet } from "./note-editor-sheet";
import { NotesList } from "./notes-list";

export function NotesScreen() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const editorSheetRef = useRef<NoteEditorSheetRef>(null);

  const {
    notes,
    isLoading,
    isRefreshing,
    error,
    searchQuery,
    setSearchQuery,
    refetch,
    createNote,
    updateNote,
    deleteNote,
  } = useNotes();

  useFocusEffect(
    useCallback(() => {
      void refetch();
    }, [refetch]),
  );

  const handleNotePress = useCallback((note: Note) => {
    editorSheetRef.current?.openEdit(note);
  }, []);

  const handleCreatePress = useCallback(() => {
    editorSheetRef.current?.openCreate();
  }, []);

  const handleSaveCreate = useCallback(
    async (data: { title: string; content: string }) => {
      await createNote(data);
    },
    [createNote],
  );

  const handleSaveUpdate = useCallback(
    async (id: string, data: { title?: string; content?: string }) => {
      await updateNote(id, data);
    },
    [updateNote],
  );

  const handleDeleteNote = useCallback(
    (id: string) => {
      void deleteNote(id);
    },
    [deleteNote],
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
          Notes
        </Text>

        <Pressable
          onPress={handleCreatePress}
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
          marginHorizontal: spacing.md,
          marginTop: 12,
          marginBottom: 8,
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
          placeholder="Search notes..."
          placeholderTextColor="#52525b"
          style={{ flex: 1, fontSize: 15, color: "#f4f4f5" }}
          clearButtonMode="while-editing"
        />
      </View>

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
        <NotesList
          notes={notes}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          onRefresh={() => {
            void refetch();
          }}
          onNotePress={handleNotePress}
          onDeleteNote={handleDeleteNote}
          onCreateNote={handleCreatePress}
        />
      )}

      {/* FAB */}
      <Pressable
        onPress={handleCreatePress}
        style={{
          position: "absolute",
          bottom: insets.bottom + 20,
          right: 20,
          width: 56,
          height: 56,
          borderRadius: 28,
          backgroundColor: "#16c1ff",
          alignItems: "center",
          justifyContent: "center",
          shadowColor: "#16c1ff",
          shadowOffset: { width: 0, height: 4 },
          shadowOpacity: 0.4,
          shadowRadius: 8,
          elevation: 8,
        }}
      >
        <AppIcon icon={Add01Icon} size={24} color="#000" />
      </Pressable>

      <NoteEditorSheet
        ref={editorSheetRef}
        onSaveCreate={handleSaveCreate}
        onSaveUpdate={handleSaveUpdate}
      />
    </View>
  );
}
