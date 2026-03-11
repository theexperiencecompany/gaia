import { useCallback } from "react";
import { Alert, Pressable, View } from "react-native";
import { AppIcon, Delete02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Note } from "../api/notes-api";

interface NoteCardProps {
  note: Note;
  onPress: (note: Note) => void;
  onDelete: (id: string) => void;
}

function formatRelativeDate(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMinutes < 1) return "Just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function NoteCard({ note, onPress, onDelete }: NoteCardProps) {
  const { spacing, fontSize } = useResponsive();

  const handleDeletePress = useCallback(() => {
    Alert.alert(
      "Delete Note",
      `Are you sure you want to delete "${note.title || "Untitled"}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => onDelete(note.id),
        },
      ],
    );
  }, [note.id, note.title, onDelete]);

  const handlePress = useCallback(() => {
    onPress(note);
  }, [onPress, note]);

  return (
    <Pressable
      onPress={handlePress}
      onLongPress={handleDeletePress}
      style={{
        backgroundColor: "#18181b",
        borderRadius: 12,
        padding: spacing.md,
        borderWidth: 1,
        borderColor: "#27272a",
        marginHorizontal: spacing.md,
        marginBottom: spacing.sm,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "flex-start",
          gap: spacing.sm,
        }}
      >
        <View style={{ flex: 1, minWidth: 0 }}>
          {note.title ? (
            <Text
              numberOfLines={1}
              style={{
                fontSize: fontSize.base,
                fontWeight: "600",
                color: "#f4f4f5",
                marginBottom: 4,
              }}
            >
              {note.title}
            </Text>
          ) : null}
          {note.content ? (
            <Text
              numberOfLines={2}
              style={{
                fontSize: fontSize.sm,
                color: "#a1a1aa",
                lineHeight: fontSize.sm * 1.5,
              }}
            >
              {note.content}
            </Text>
          ) : (
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#52525b",
                fontStyle: "italic",
              }}
            >
              Empty note
            </Text>
          )}
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#52525b",
              marginTop: spacing.xs,
            }}
          >
            {formatRelativeDate(note.updated_at)}
          </Text>
        </View>

        <Pressable
          onPress={handleDeletePress}
          hitSlop={8}
          style={{
            width: 28,
            height: 28,
            borderRadius: 8,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(239,68,68,0.08)",
            flexShrink: 0,
          }}
        >
          <AppIcon icon={Delete02Icon} size={14} color="#ef4444" />
        </Pressable>
      </View>
    </Pressable>
  );
}
