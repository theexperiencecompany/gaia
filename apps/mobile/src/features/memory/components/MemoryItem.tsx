import { useRef } from "react";
import { Pressable, View } from "react-native";
import { Swipeable } from "react-native-gesture-handler";
import { AppIcon, Delete02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Memory } from "../api/memory-api";

interface MemoryItemProps {
  memory: Memory;
  onDelete: (id: string) => void;
}

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`;
  return `${Math.floor(diffDays / 365)} years ago`;
}

export function MemoryItem({ memory, onDelete }: MemoryItemProps) {
  const { spacing, fontSize } = useResponsive();
  const swipeableRef = useRef<Swipeable | null>(null);

  const renderRightActions = () => (
    <Pressable
      onPress={() => {
        swipeableRef.current?.close();
        onDelete(memory.id);
      }}
      style={{
        backgroundColor: "#ef4444",
        justifyContent: "center",
        alignItems: "center",
        paddingHorizontal: spacing.lg,
        borderRadius: 12,
        marginLeft: spacing.xs,
        marginBottom: spacing.sm,
      }}
    >
      <AppIcon icon={Delete02Icon} size={20} color="#fff" />
    </Pressable>
  );

  return (
    <Swipeable
      ref={swipeableRef}
      renderRightActions={renderRightActions}
      overshootRight={false}
    >
      <View
        style={{
          backgroundColor: "#1c1c1e",
          borderRadius: 12,
          padding: spacing.md,
          marginBottom: spacing.sm,
          gap: spacing.xs,
        }}
      >
        <Text
          style={{
            fontSize: fontSize.sm,
            color: "#e4e4e7",
            lineHeight: 20,
          }}
          numberOfLines={4}
        >
          {memory.content}
        </Text>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: spacing.xs,
          }}
        >
          {memory.source_conversation_id ? (
            <Text style={{ fontSize: fontSize.xs, color: "#52525b" }}>
              From conversation
            </Text>
          ) : (
            <View />
          )}
          <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
            {formatRelativeDate(memory.created_at)}
          </Text>
        </View>
      </View>
    </Swipeable>
  );
}
