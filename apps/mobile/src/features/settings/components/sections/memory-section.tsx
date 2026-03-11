import { Swipeable } from "react-native-gesture-handler";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  Pressable,
  TextInput,
  View,
} from "react-native";
import { Add01Icon, AppIcon, Delete02Icon, Search01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { apiService } from "@/lib/api";
import { useResponsive } from "@/lib/responsive";

interface Memory {
  id: string;
  content: string;
  created_at: string;
}

interface MemoriesResponse {
  memories: Memory[];
}

export function MemorySection() {
  const { spacing, fontSize } = useResponsive();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [search, setSearch] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newMemoryText, setNewMemoryText] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const swipeableRefs = useRef<Map<string, Swipeable | null>>(new Map());

  const loadMemories = async () => {
    setIsLoading(true);
    try {
      const response = await apiService.get<MemoriesResponse>("/memories");
      setMemories(response.memories ?? []);
    } catch {
      // silently fail — memories may not be available in all environments
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadMemories();
  }, []);

  const filteredMemories = memories.filter((m) =>
    m.content.toLowerCase().includes(search.toLowerCase()),
  );

  const handleDelete = async (id: string) => {
    setMemories((prev) => prev.filter((m) => m.id !== id));
    try {
      await apiService.delete(`/memories/${id}`);
    } catch {
      // Restore on failure
      void loadMemories();
    }
  };

  const handleAdd = async () => {
    const trimmed = newMemoryText.trim();
    if (!trimmed) return;
    setIsSaving(true);
    try {
      await apiService.post("/memories", { content: trimmed });
      setNewMemoryText("");
      setShowAddModal(false);
      await loadMemories();
    } catch {
      Alert.alert("Error", "Failed to save memory. Please try again.");
    } finally {
      setIsSaving(false);
    }
  };

  const renderRightActions = (memoryId: string) => (
    <Pressable
      onPress={() => {
        swipeableRefs.current.get(memoryId)?.close();
        void handleDelete(memoryId);
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
    <View style={{ flex: 1, gap: spacing.md, padding: spacing.md }}>
      {/* Search bar */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          backgroundColor: "#1c1c1e",
          borderRadius: 12,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
          gap: spacing.sm,
        }}
      >
        <AppIcon icon={Search01Icon} size={16} color="#71717a" />
        <TextInput
          value={search}
          onChangeText={setSearch}
          placeholder="Search memories..."
          placeholderTextColor="#52525b"
          style={{ flex: 1, color: "#fff", fontSize: fontSize.sm }}
        />
      </View>

      {isLoading ? (
        <View
          style={{
            alignItems: "center",
            paddingVertical: spacing.xl * 2,
          }}
        >
          <ActivityIndicator color="#00bbff" />
        </View>
      ) : filteredMemories.length === 0 ? (
        <View
          style={{
            alignItems: "center",
            paddingVertical: spacing.xl * 2,
          }}
        >
          <Text style={{ color: "#71717a", fontSize: fontSize.sm }}>
            {search ? `No memories matching "${search}"` : "No memories yet"}
          </Text>
        </View>
      ) : (
        <FlatList
          data={filteredMemories}
          keyExtractor={(m) => m.id}
          scrollEnabled={false}
          renderItem={({ item }) => (
            <Swipeable
              ref={(r) => {
                swipeableRefs.current.set(item.id, r);
              }}
              renderRightActions={() => renderRightActions(item.id)}
              overshootRight={false}
            >
              <View
                style={{
                  backgroundColor: "#1c1c1e",
                  borderRadius: 12,
                  padding: spacing.md,
                  marginBottom: spacing.sm,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: "#e4e4e7",
                    lineHeight: 20,
                  }}
                >
                  {item.content}
                </Text>
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#71717a",
                    marginTop: spacing.xs,
                  }}
                >
                  {new Date(item.created_at).toLocaleDateString()}
                </Text>
              </View>
            </Swipeable>
          )}
        />
      )}

      {/* Add button */}
      <Pressable
        onPress={() => setShowAddModal(true)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: spacing.sm,
          padding: spacing.md,
          borderRadius: 12,
          borderWidth: 1,
          borderStyle: "dashed",
          borderColor: "rgba(0,187,255,0.3)",
          backgroundColor: "rgba(0,187,255,0.05)",
        }}
      >
        <AppIcon icon={Add01Icon} size={16} color="#00bbff" />
        <Text
          style={{
            color: "#00bbff",
            fontSize: fontSize.sm,
            fontWeight: "500",
          }}
        >
          Add Memory
        </Text>
      </Pressable>

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
              backgroundColor: "#1c1c1e",
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
                color: "#fff",
              }}
            >
              Add Memory
            </Text>

            <TextInput
              value={newMemoryText}
              onChangeText={setNewMemoryText}
              placeholder="What should GAIA remember?"
              placeholderTextColor="#52525b"
              multiline
              numberOfLines={4}
              autoFocus
              style={{
                backgroundColor: "#2c2c2e",
                borderRadius: 10,
                padding: spacing.md,
                color: "#fff",
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
                <Text style={{ color: "#8e8e93", fontSize: fontSize.sm }}>
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
                  backgroundColor: "#00bbff",
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
