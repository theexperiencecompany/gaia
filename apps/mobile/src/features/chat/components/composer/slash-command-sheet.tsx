import {
  BottomSheetFlatList,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  Search01Icon,
  ShieldUserIcon,
  Wrench01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { apiService } from "@/lib/api";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

interface ToolInfo {
  name: string;
  category: string;
  display_name: string;
  icon_url?: string;
  requires_integration: boolean;
}

interface ToolsListResponse {
  tools: ToolInfo[];
  total_count: number;
  categories: string[];
}

export interface SlashCommandSheetRef {
  open: () => void;
  close: () => void;
}

interface SlashCommandSheetProps {
  onSelectTool: (toolName: string, toolCategory: string) => void;
}

function formatToolName(name: string): string {
  return name
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ")
    .replace(/\s+tool$/i, "")
    .trim();
}

function formatCategoryName(category: string): string {
  return category
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export const SlashCommandSheet = forwardRef<
  SlashCommandSheetRef,
  SlashCommandSheetProps
>(({ onSelectTool }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);
  const { spacing, fontSize, iconSize } = useResponsive();

  useImperativeHandle(ref, () => ({
    open: () => {
      setIsOpen(true);
      if (!hasLoaded) {
        loadTools();
      }
    },
    close: () => {
      setIsOpen(false);
    },
  }));

  const loadTools = async () => {
    setIsLoading(true);
    try {
      const data = await apiService.get<ToolsListResponse>("/tools");
      setTools(data.tools);
      setCategories(data.categories);
      setHasLoaded(true);
    } catch (error) {
      console.error("Failed to load tools:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (!hasLoaded) return;
    // Reset search when sheet reopens
    setSearchQuery("");
    setSelectedCategory("all");
  }, [hasLoaded]);

  const filteredTools = useMemo(() => {
    let filtered = tools;

    if (selectedCategory !== "all") {
      filtered = filtered.filter((tool) => tool.category === selectedCategory);
    }

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (tool) =>
          formatToolName(tool.name).toLowerCase().includes(query) ||
          tool.category.toLowerCase().includes(query) ||
          tool.display_name?.toLowerCase().includes(query),
      );
    }

    return filtered;
  }, [tools, selectedCategory, searchQuery]);

  const handleSelect = useCallback(
    (tool: ToolInfo) => {
      onSelectTool(tool.name, tool.category);
      setIsOpen(false);
      setSearchQuery("");
    },
    [onSelectTool],
  );

  const renderToolItem = useCallback(
    ({ item }: { item: ToolInfo }) => {
      const categoryIcon = getToolCategoryIcon(
        item.category,
        { size: 16, showBackground: true, pulsating: false },
        item.icon_url,
      );
      const isLocked = !!item.requires_integration;

      return (
        <Pressable
          onPress={() => handleSelect(item)}
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm + 2,
            marginHorizontal: spacing.sm,
            borderRadius: 12,
          }}
          android_ripple={{ color: "rgba(255,255,255,0.08)" }}
        >
          <View style={{ position: "relative", marginRight: spacing.sm }}>
            <View
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                backgroundColor: "#27272a",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {categoryIcon ?? (
                <AppIcon
                  icon={Wrench01Icon}
                  size={iconSize.sm}
                  color="#a1a1aa"
                />
              )}
            </View>
            {isLocked && (
              <View
                style={{
                  position: "absolute",
                  bottom: -2,
                  right: -2,
                  width: 12,
                  height: 12,
                  borderRadius: 6,
                  backgroundColor: "#1c1c1e",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <AppIcon icon={ShieldUserIcon} size={8} color="#71717a" />
              </View>
            )}
          </View>

          <View style={{ flex: 1, marginRight: spacing.sm }}>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#e4e4e7",
                fontWeight: "400",
              }}
              numberOfLines={1}
            >
              {formatToolName(item.name)}
            </Text>
          </View>

          <View
            style={{
              backgroundColor: "#27272a",
              paddingHorizontal: spacing.sm,
              paddingVertical: 2,
              borderRadius: 10,
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.06)",
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#71717a",
              }}
              numberOfLines={1}
            >
              {formatCategoryName(item.display_name || item.category)}
            </Text>
          </View>
        </Pressable>
      );
    },
    [handleSelect, spacing, fontSize, iconSize],
  );

  const allCategories = useMemo(() => ["all", ...categories], [categories]);

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["60%", "85%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#141414" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
          keyboardBehavior="interactive"
          keyboardBlurBehavior="restore"
        >
          {/* Header */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              paddingHorizontal: spacing.md,
              paddingBottom: spacing.sm,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.lg,
                fontWeight: "600",
                color: "#ffffff",
              }}
            >
              Tools
            </Text>
            <Pressable
              onPress={() => setIsOpen(false)}
              style={{
                width: 32,
                height: 32,
                borderRadius: 16,
                backgroundColor: "rgba(142,142,147,0.1)",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <AppIcon icon={Cancel01Icon} size={18} color="#8e8e93" />
            </Pressable>
          </View>

          {/* Search */}
          <View
            style={{
              paddingHorizontal: spacing.md,
              paddingBottom: spacing.sm,
            }}
          >
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                borderRadius: 12,
                paddingHorizontal: spacing.sm + 2,
                paddingVertical: spacing.sm,
                backgroundColor: "rgba(142,142,147,0.1)",
              }}
            >
              <AppIcon icon={Search01Icon} size={18} color="#8e8e93" />
              <BottomSheetTextInput
                style={{
                  flex: 1,
                  marginLeft: spacing.sm,
                  color: "#ffffff",
                  fontSize: fontSize.sm,
                  padding: 0,
                }}
                placeholder="Search tools..."
                placeholderTextColor="#6b6b6b"
                value={searchQuery}
                onChangeText={setSearchQuery}
              />
            </View>
          </View>

          {/* Category tabs */}
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={{ maxHeight: 44, paddingBottom: spacing.sm }}
            contentContainerStyle={{
              paddingHorizontal: spacing.md,
              gap: spacing.xs,
            }}
          >
            {allCategories.map((category) => {
              const isActive = selectedCategory === category;
              return (
                <Pressable
                  key={category}
                  onPress={() => setSelectedCategory(category)}
                  style={{
                    paddingHorizontal: spacing.sm + 2,
                    paddingVertical: spacing.xs + 2,
                    borderRadius: 12,
                    backgroundColor: isActive
                      ? "rgba(63,63,70,0.5)"
                      : "transparent",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      fontWeight: "500",
                      color: isActive ? "#ffffff" : "#71717a",
                    }}
                    numberOfLines={1}
                  >
                    {category === "all" ? "All" : formatCategoryName(category)}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>

          {/* Tool list */}
          {isLoading ? (
            <View
              style={{
                flex: 1,
                alignItems: "center",
                justifyContent: "center",
                paddingVertical: 32,
              }}
            >
              <ActivityIndicator size="large" color="#8e8e93" />
              <Text
                style={{
                  color: "#6b6b6b",
                  fontSize: fontSize.sm,
                  marginTop: spacing.sm,
                }}
              >
                Loading tools...
              </Text>
            </View>
          ) : (
            <BottomSheetFlatList
              data={filteredTools}
              keyExtractor={(item: ToolInfo) => item.name}
              renderItem={renderToolItem}
              contentContainerStyle={{
                paddingBottom: 24,
                paddingTop: spacing.xs,
              }}
              showsVerticalScrollIndicator={false}
              ListEmptyComponent={
                <View
                  style={{
                    alignItems: "center",
                    justifyContent: "center",
                    paddingVertical: 32,
                  }}
                >
                  <Text
                    style={{
                      color: "#6b6b6b",
                      fontSize: fontSize.sm,
                    }}
                  >
                    No tools found
                  </Text>
                </View>
              }
            />
          )}
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

SlashCommandSheet.displayName = "SlashCommandSheet";
