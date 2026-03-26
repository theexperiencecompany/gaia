import { useCallback } from "react";
import { FlatList, Pressable, RefreshControl, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Add01Icon, AppIcon, FileEmpty02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Note } from "../api/notes-api";
import { NoteCard } from "./note-card";

interface NotesListProps {
  notes: Note[];
  isLoading: boolean;
  isRefreshing: boolean;
  onRefresh: () => void;
  onNotePress: (note: Note) => void;
  onDeleteNote: (id: string) => void;
  onCreateNote: () => void;
}

function NotesSkeleton() {
  const { spacing } = useResponsive();
  return (
    <View style={{ paddingTop: spacing.sm }}>
      {Array.from({ length: 6 }).map((_, i) => {
        const key = `skeleton-${i}`;
        return (
          <View
            key={key}
            style={{
              backgroundColor: "#18181b",
              borderRadius: 12,
              padding: spacing.md,
              borderWidth: 1,
              borderColor: "#27272a",
              marginHorizontal: spacing.md,
              marginBottom: spacing.sm,
              gap: 8,
            }}
          >
            <View
              style={{
                height: 15,
                borderRadius: 6,
                backgroundColor: "rgba(255,255,255,0.06)",
                width: `${50 + (i % 4) * 12}%`,
              }}
            />
            <View
              style={{
                height: 13,
                borderRadius: 6,
                backgroundColor: "rgba(255,255,255,0.04)",
                width: `${70 + (i % 3) * 8}%`,
              }}
            />
          </View>
        );
      })}
    </View>
  );
}

export function NotesList({
  notes,
  isLoading,
  isRefreshing,
  onRefresh,
  onNotePress,
  onDeleteNote,
  onCreateNote,
}: NotesListProps) {
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();

  const renderItem = useCallback(
    ({ item }: { item: Note }) => (
      <NoteCard note={item} onPress={onNotePress} onDelete={onDeleteNote} />
    ),
    [onNotePress, onDeleteNote],
  );

  const keyExtractor = useCallback((item: Note) => item.id, []);

  if (isLoading) {
    return <NotesSkeleton />;
  }

  return (
    <FlatList
      data={notes}
      keyExtractor={keyExtractor}
      renderItem={renderItem}
      contentContainerStyle={{
        flexGrow: 1,
        paddingTop: spacing.sm,
        paddingBottom: insets.bottom + 96,
      }}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={onRefresh}
          tintColor="#16c1ff"
        />
      }
      ListEmptyComponent={
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingVertical: spacing.xl * 3,
            gap: spacing.md,
          }}
        >
          <View
            style={{
              width: 72,
              height: 72,
              borderRadius: 36,
              backgroundColor: "rgba(255,255,255,0.04)",
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.06)",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AppIcon icon={FileEmpty02Icon} size={36} color="#3f3f46" />
          </View>
          <View style={{ alignItems: "center", gap: 6 }}>
            <Text
              style={{
                fontSize: fontSize.base,
                fontWeight: "600",
                color: "#d4d4d8",
                textAlign: "center",
              }}
            >
              No notes yet
            </Text>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#71717a",
                textAlign: "center",
                maxWidth: 240,
              }}
            >
              Tap the button below to create your first note
            </Text>
          </View>
          <Pressable
            onPress={onCreateNote}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
              borderRadius: 10,
              backgroundColor: "rgba(22,193,255,0.12)",
              borderWidth: 1,
              borderColor: "rgba(22,193,255,0.2)",
            }}
          >
            <AppIcon icon={Add01Icon} size={16} color="#16c1ff" />
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: "#16c1ff",
              }}
            >
              Create note
            </Text>
          </Pressable>
        </View>
      }
    />
  );
}
