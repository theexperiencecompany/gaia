import { Button, Card, Spinner, TextField } from "heroui-native";
import { useEffect, useRef, useState } from "react";
import { Alert, FlatList, Modal, Pressable, View } from "react-native";
import { Swipeable } from "react-native-gesture-handler";
import {
  Add01Icon,
  AppIcon,
  Delete02Icon,
  Search01Icon,
} from "@/components/icons";
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
      <TextField>
        <TextField.Input
          value={search}
          onChangeText={setSearch}
          placeholder="Search memories..."
        >
          <TextField.InputStartContent>
            <AppIcon icon={Search01Icon} size={16} color="#71717a" />
          </TextField.InputStartContent>
        </TextField.Input>
      </TextField>

      {isLoading ? (
        <View
          style={{
            alignItems: "center",
            paddingVertical: spacing.xl * 2,
          }}
        >
          <Spinner />
        </View>
      ) : filteredMemories.length === 0 ? (
        <Card variant="secondary" className="rounded-3xl bg-surface">
          <Card.Body className="items-center px-5 py-10">
            <Text style={{ color: "#71717a", fontSize: fontSize.sm }}>
              {search ? `No memories matching "${search}"` : "No memories yet"}
            </Text>
          </Card.Body>
        </Card>
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
              <Card variant="secondary" className="mb-2 rounded-3xl bg-surface">
                <Card.Body className="px-4 py-4">
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
                </Card.Body>
              </Card>
            </Swipeable>
          )}
        />
      )}

      {/* Add button */}
      <Button
        onPress={() => setShowAddModal(true)}
        variant="tertiary"
        className="bg-primary/10"
      >
        <AppIcon icon={Add01Icon} size={16} color="#00bbff" />
        <Button.Label className="text-primary">Add Memory</Button.Label>
      </Button>

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
          <Card
            variant="secondary"
            className="w-full rounded-3xl bg-surface"
            onTouchEnd={(e) => e.stopPropagation()}
          >
            <Card.Body className="gap-4 px-5 py-5">
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#fff",
                }}
              >
                Add Memory
              </Text>

              <TextField>
                <TextField.Input
                  value={newMemoryText}
                  onChangeText={setNewMemoryText}
                  placeholder="What should GAIA remember?"
                  multiline
                  numberOfLines={4}
                  autoFocus
                  style={{ minHeight: 100 }}
                />
              </TextField>

              <View style={{ flexDirection: "row", gap: spacing.sm }}>
                <Button
                  onPress={() => {
                    setShowAddModal(false);
                    setNewMemoryText("");
                  }}
                  variant="tertiary"
                  className="flex-1 bg-white/10"
                >
                  <Button.Label className="text-muted">Cancel</Button.Label>
                </Button>
                <Button
                  onPress={() => void handleAdd()}
                  isDisabled={isSaving || !newMemoryText.trim()}
                  className="flex-1 bg-primary"
                >
                  {isSaving ? <Spinner /> : <Button.Label>Save</Button.Label>}
                </Button>
              </View>
            </Card.Body>
          </Card>
        </Pressable>
      </Modal>
    </View>
  );
}
