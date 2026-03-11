import { useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  Pressable,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Add01Icon,
  AppIcon,
  ArrowLeft01Icon,
  BrainIcon,
  Delete02Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Memory } from "../api/memory-api";
import { useMemory } from "../hooks/useMemory";
import { MemoryItem } from "./MemoryItem";

const C = {
  bg: "#060a14",
  surface: "#1c1c1e",
  surfaceAlt: "#2c2c2e",
  divider: "rgba(255,255,255,0.06)",
  text: "#ffffff",
  textMuted: "#8e8e93",
  textSubtle: "#52525b",
  primary: "#00bbff",
  primaryBg: "rgba(0,187,255,0.1)",
  primaryBorder: "rgba(0,187,255,0.3)",
  danger: "#ef4444",
  dangerBg: "rgba(239,68,68,0.12)",
  dangerBorder: "rgba(239,68,68,0.3)",
  headerBorder: "rgba(255,255,255,0.08)",
} as const;

function EmptyState({ search }: { search: string }) {
  const { spacing, fontSize } = useResponsive();

  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingVertical: spacing.xl * 3,
        gap: spacing.md,
      }}
    >
      <AppIcon icon={BrainIcon} size={40} color={C.textSubtle} />
      <Text
        style={{
          fontSize: fontSize.base,
          color: C.textMuted,
          fontWeight: "500",
        }}
      >
        {search ? `No memories matching "${search}"` : "No memories yet"}
      </Text>
      {!search && (
        <Text
          style={{
            fontSize: fontSize.sm,
            color: C.textSubtle,
            textAlign: "center",
            maxWidth: 260,
          }}
        >
          GAIA will automatically remember important things from your
          conversations.
        </Text>
      )}
    </View>
  );
}

export function MemoryScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();
  const {
    memories,
    isLoading,
    isRefreshing,
    search,
    setSearch,
    refetch,
    createMemory,
    deleteMemory,
    clearAll,
  } = useMemory();

  const [showAddModal, setShowAddModal] = useState(false);
  const [newMemoryText, setNewMemoryText] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const handleDelete = useCallback(
    (id: string) => {
      void deleteMemory(id);
    },
    [deleteMemory],
  );

  const handleAdd = useCallback(async () => {
    const trimmed = newMemoryText.trim();
    if (!trimmed) return;
    setIsSaving(true);
    try {
      await createMemory(trimmed);
      setNewMemoryText("");
      setShowAddModal(false);
    } catch {
      Alert.alert("Error", "Failed to save memory. Please try again.");
    } finally {
      setIsSaving(false);
    }
  }, [newMemoryText, createMemory]);

  const handleClearAll = useCallback(() => {
    Alert.alert(
      "Clear All Memory",
      "This will permanently delete all memories. GAIA will no longer remember anything from past conversations. This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Clear All",
          style: "destructive",
          onPress: () => void clearAll(),
        },
      ],
    );
  }, [clearAll]);

  const renderItem = useCallback(
    ({ item }: { item: Memory }) => (
      <MemoryItem memory={item} onDelete={handleDelete} />
    ),
    [handleDelete],
  );

  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: C.headerBorder,
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.md,
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
          <AppIcon icon={ArrowLeft01Icon} size={18} color={C.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "600",
              color: C.text,
            }}
          >
            Memory
          </Text>
          {!isLoading && (
            <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
              {memories.length} {memories.length === 1 ? "memory" : "memories"}
            </Text>
          )}
        </View>
        <Pressable
          onPress={() => setShowAddModal(true)}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: C.primaryBg,
          }}
        >
          <AppIcon icon={Add01Icon} size={18} color={C.primary} />
        </Pressable>
      </View>

      {/* Search bar */}
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
          borderBottomWidth: 1,
          borderBottomColor: C.headerBorder,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            backgroundColor: C.surface,
            borderRadius: 12,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm,
            gap: spacing.sm,
          }}
        >
          <AppIcon icon={Search01Icon} size={16} color={C.textMuted} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="Search memories..."
            placeholderTextColor={C.textSubtle}
            style={{ flex: 1, color: C.text, fontSize: fontSize.sm }}
          />
        </View>
      </View>

      {/* Content */}
      {isLoading ? (
        <View
          style={{ flex: 1, alignItems: "center", justifyContent: "center" }}
        >
          <ActivityIndicator color={C.primary} />
        </View>
      ) : (
        <FlatList
          data={memories}
          keyExtractor={(m) => m.id}
          renderItem={renderItem}
          onRefresh={refetch}
          refreshing={isRefreshing}
          contentContainerStyle={{
            padding: spacing.md,
            paddingBottom: insets.bottom + spacing.xl * 3,
            flexGrow: 1,
          }}
          ListEmptyComponent={<EmptyState search={search} />}
        />
      )}

      {/* Clear All button */}
      {memories.length > 0 && (
        <View
          style={{
            position: "absolute",
            bottom: insets.bottom + spacing.md,
            left: spacing.md,
            right: spacing.md,
          }}
        >
          <Pressable
            onPress={handleClearAll}
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: spacing.sm,
              padding: spacing.md,
              borderRadius: 12,
              borderWidth: 1,
              borderColor: C.dangerBorder,
              backgroundColor: C.dangerBg,
            }}
          >
            <AppIcon icon={Delete02Icon} size={16} color={C.danger} />
            <Text
              style={{
                color: C.danger,
                fontSize: fontSize.sm,
                fontWeight: "500",
              }}
            >
              Clear All Memory
            </Text>
          </Pressable>
        </View>
      )}

      {/* Add memory modal */}
      <Modal
        visible={showAddModal}
        transparent
        animationType="fade"
        onRequestClose={() => setShowAddModal(false)}
      >
        <Pressable
          onPress={() => setShowAddModal(false)}
          style={{
            flex: 1,
            backgroundColor: "rgba(0,0,0,0.6)",
            justifyContent: "center",
            alignItems: "center",
            padding: spacing.lg,
          }}
        >
          <Pressable
            onPress={(e) => e.stopPropagation()}
            style={{
              backgroundColor: C.surface,
              borderRadius: 16,
              padding: spacing.lg,
              width: "100%",
              gap: spacing.md,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.base,
                fontWeight: "600",
                color: C.text,
              }}
            >
              Add Memory
            </Text>

            <TextInput
              value={newMemoryText}
              onChangeText={setNewMemoryText}
              placeholder="What should GAIA remember?"
              placeholderTextColor={C.textSubtle}
              multiline
              numberOfLines={4}
              autoFocus
              style={{
                backgroundColor: C.surfaceAlt,
                borderRadius: 10,
                padding: spacing.md,
                color: C.text,
                fontSize: fontSize.sm,
                minHeight: 100,
                textAlignVertical: "top",
              }}
            />

            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Pressable
                onPress={() => {
                  setShowAddModal(false);
                  setNewMemoryText("");
                }}
                style={{
                  flex: 1,
                  padding: spacing.md,
                  borderRadius: 10,
                  backgroundColor: "rgba(255,255,255,0.06)",
                  alignItems: "center",
                }}
              >
                <Text style={{ color: C.textMuted, fontSize: fontSize.sm }}>
                  Cancel
                </Text>
              </Pressable>
              <Pressable
                onPress={() => void handleAdd()}
                disabled={isSaving || !newMemoryText.trim()}
                style={{
                  flex: 1,
                  padding: spacing.md,
                  borderRadius: 10,
                  backgroundColor: C.primary,
                  alignItems: "center",
                  opacity: isSaving || !newMemoryText.trim() ? 0.5 : 1,
                }}
              >
                {isSaving ? (
                  <ActivityIndicator size="small" color="#000" />
                ) : (
                  <Text
                    style={{
                      color: "#000",
                      fontSize: fontSize.sm,
                      fontWeight: "600",
                    }}
                  >
                    Save
                  </Text>
                )}
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}
