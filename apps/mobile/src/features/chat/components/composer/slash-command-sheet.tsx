import {
  BottomSheetFlatList,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import { Spinner } from "heroui-native";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { Pressable, ScrollView, View } from "react-native";
import {
  AlertCircleIcon,
  AppIcon,
  Cancel01Icon,
  ConnectIcon,
  LayoutGridIcon,
  Search01Icon,
  ShieldUserIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  type ToolInfo,
  useToolsList,
} from "@/features/chat/hooks/useToolsList";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";
import { haptics } from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

const SHEET_SNAP_POINTS: Array<string | number> = ["70%", "92%"];
const SHEET_BACKGROUND = "#141414";
const SHEET_HANDLE_COLOR = "rgba(255,255,255,0.25)";
const SKELETON_ROW_COUNT = 6;
const ZINC_500 = "#71717a";
const ZINC_400 = "#a1a1aa";
const ZINC_200 = "#e4e4e7";
const PRIMARY = "#00bbff";
const RED_400 = "#f87171";
const RED_TILE_BG = "rgba(239,68,68,0.15)";
const PRIMARY_CHIP_BG = "rgba(0,187,255,0.15)";
const PRIMARY_CHIP_BG_PRESSED = "rgba(0,187,255,0.25)";
const ROW_BG_PRESSED = "rgba(63,63,70,0.4)";
const SECTION_BG = "#27272a";
const SEARCH_BG = "rgba(255,255,255,0.05)";
const HEADER_CLOSE_BG = "rgba(63,63,70,0.6)";
const CHIP_ACTIVE_BG = "rgba(63,63,70,0.55)";
const CHIP_INACTIVE_BG = "rgba(255,255,255,0.05)";

interface EnhancedTool extends ToolInfo {
  isLocked: boolean;
}

type ListItem =
  | { type: "tool"; tool: EnhancedTool }
  | {
      type: "locked-section";
      category: string;
      categoryDisplayName: string;
      tools: EnhancedTool[];
      iconUrl?: string;
      isConnected: boolean;
      isConnecting: boolean;
    }
  | { type: "locked-tool"; tool: EnhancedTool };

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

function findIntegration(
  integrations: Integration[],
  category: string,
): Integration | undefined {
  return integrations.find(
    (item) => item.id.toLowerCase() === category.toLowerCase(),
  );
}

interface SkeletonRowProps {
  spacing: { sm: number; md: number };
}

function SkeletonRow({ spacing }: SkeletonRowProps) {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.sm + 4,
        paddingVertical: spacing.sm + 2,
        gap: spacing.sm + 2,
      }}
    >
      <View
        style={{
          width: 32,
          height: 32,
          borderRadius: 8,
          backgroundColor: "rgba(63,63,70,0.4)",
        }}
      />
      <View
        style={{
          flex: 1,
          height: 12,
          maxWidth: "60%",
          borderRadius: 6,
          backgroundColor: "rgba(63,63,70,0.4)",
        }}
      />
    </View>
  );
}

interface SkeletonListProps {
  spacing: { sm: number; md: number };
}

function SkeletonList({ spacing }: SkeletonListProps) {
  return (
    <View style={{ paddingTop: spacing.sm }}>
      {Array.from({ length: SKELETON_ROW_COUNT }).map((_, idx) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: skeleton placeholders
        <SkeletonRow key={`skeleton-${idx}`} spacing={spacing} />
      ))}
    </View>
  );
}

interface ErrorStateProps {
  onRetry: () => void;
  spacing: { sm: number; md: number; lg: number };
  fontSize: { sm: number; xs: number };
}

function ErrorState({ onRetry, spacing, fontSize }: ErrorStateProps) {
  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        padding: spacing.lg,
        gap: 16,
      }}
    >
      <View
        style={{
          width: 64,
          height: 64,
          borderRadius: 32,
          backgroundColor: "rgba(24,24,27,0.5)",
          borderWidth: 1,
          borderColor: "#27272a",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon icon={AlertCircleIcon} size={28} color="#52525b" />
      </View>
      <View style={{ alignItems: "center", gap: 4 }}>
        <Text
          style={{
            color: "#ffffff",
            fontSize: 16,
            fontWeight: "600",
          }}
        >
          Couldn't load tools
        </Text>
        <Text
          style={{
            color: ZINC_500,
            fontSize: 14,
            textAlign: "center",
          }}
        >
          Check your connection and try again.
        </Text>
      </View>
      <Pressable
        onPress={onRetry}
        style={{
          marginTop: 8,
          borderRadius: 12,
          borderWidth: 1,
          borderColor: "#3f3f46",
          paddingVertical: 10,
          paddingHorizontal: 18,
        }}
      >
        <Text
          style={{
            color: ZINC_200,
            fontSize: fontSize.sm,
            fontWeight: "500",
          }}
        >
          Retry
        </Text>
      </Pressable>
    </View>
  );
}

interface EmptyStateProps {
  hasQuery: boolean;
  spacing: { lg: number };
}

function EmptyState({ hasQuery, spacing }: EmptyStateProps) {
  return (
    <View
      style={{
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: spacing.lg,
        paddingVertical: 56,
        gap: 16,
      }}
    >
      <View
        style={{
          width: 64,
          height: 64,
          borderRadius: 32,
          backgroundColor: "rgba(24,24,27,0.5)",
          borderWidth: 1,
          borderColor: "#27272a",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon
          icon={hasQuery ? Search01Icon : LayoutGridIcon}
          size={28}
          color="#52525b"
        />
      </View>
      <View style={{ alignItems: "center", gap: 4 }}>
        <Text
          style={{
            color: "#ffffff",
            fontSize: 16,
            fontWeight: "600",
          }}
        >
          {hasQuery ? "No tools found" : "No tools available"}
        </Text>
        <Text
          style={{
            color: ZINC_500,
            fontSize: 14,
            textAlign: "center",
          }}
        >
          {hasQuery
            ? "Try a different search term."
            : "Connect an integration to unlock more tools."}
        </Text>
      </View>
    </View>
  );
}

export const SlashCommandSheet = forwardRef<
  SlashCommandSheetRef,
  SlashCommandSheetProps
>(({ onSelectTool }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [connectingCategory, setConnectingCategory] = useState<string | null>(
    null,
  );
  const { spacing, fontSize, moderateScale } = useResponsive();

  const { integrations, connect } = useIntegrations();
  const {
    tools,
    categories,
    isLoading,
    isError,
    refetch: refetchTools,
  } = useToolsList(isOpen);

  useImperativeHandle(
    ref,
    () => ({
      open: () => {
        setIsOpen(true);
        setSearchQuery("");
        setSelectedCategory("all");
      },
      close: () => {
        setIsOpen(false);
      },
    }),
    [],
  );

  // Build enhanced tools with isLocked computed from integration status —
  // mirrors web's useToolsWithIntegrations.
  const enhancedTools = useMemo<EnhancedTool[]>(() => {
    return tools.map((tool) => {
      if (!tool.requires_integration) {
        return { ...tool, isLocked: false };
      }
      const integration = findIntegration(integrations, tool.category);
      const isLocked = !integration || integration.status !== "connected";
      return { ...tool, isLocked };
    });
  }, [tools, integrations]);

  // Map: category id -> { displayName, iconUrl } from tools data
  const categoryDisplayMap = useMemo(() => {
    const map: Record<string, { displayName: string; iconUrl?: string }> = {};
    tools.forEach((tool) => {
      if (!map[tool.category]) {
        map[tool.category] = {
          displayName: tool.display_name,
          iconUrl: tool.icon_url,
        };
      }
    });
    return map;
  }, [tools]);

  useEffect(() => {
    if (!isOpen) return;
    setSearchQuery("");
  }, [isOpen]);

  // Reset category selection when search starts (existing behavior).
  useEffect(() => {
    if (searchQuery.trim() && selectedCategory !== "all") {
      setSelectedCategory("all");
    }
  }, [searchQuery, selectedCategory]);

  // Filter by category + search
  const filteredTools = useMemo(() => {
    let filtered = enhancedTools;

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
  }, [enhancedTools, selectedCategory, searchQuery]);

  // Build the list: unlocked tools first, then grouped locked sections.
  const listItems = useMemo<ListItem[]>(() => {
    const items: ListItem[] = [];
    const unlocked: EnhancedTool[] = [];
    const lockedByCategory: Record<string, EnhancedTool[]> = {};

    filteredTools.forEach((tool) => {
      if (tool.isLocked) {
        if (!lockedByCategory[tool.category]) {
          lockedByCategory[tool.category] = [];
        }
        lockedByCategory[tool.category].push(tool);
      } else {
        unlocked.push(tool);
      }
    });

    unlocked.forEach((tool) => items.push({ type: "tool", tool }));

    Object.entries(lockedByCategory).forEach(([category, categoryTools]) => {
      const first = categoryTools[0];
      const integration = findIntegration(integrations, category);
      items.push({
        type: "locked-section",
        category,
        categoryDisplayName: first.display_name || formatCategoryName(category),
        tools: categoryTools,
        iconUrl: integration?.iconUrl ?? categoryDisplayMap[category]?.iconUrl,
        isConnected: integration?.status === "connected",
        isConnecting: connectingCategory === category,
      });
      categoryTools.forEach((tool) =>
        items.push({ type: "locked-tool", tool }),
      );
    });

    return items;
  }, [filteredTools, integrations, categoryDisplayMap, connectingCategory]);

  const handleSelect = useCallback(
    (tool: EnhancedTool) => {
      if (tool.isLocked) return;
      void haptics.light();
      onSelectTool(tool.name, tool.category);
      setIsOpen(false);
      setSearchQuery("");
    },
    [onSelectTool],
  );

  const handleConnect = useCallback(
    async (integrationId: string) => {
      if (connectingCategory) return;
      void haptics.light();
      setConnectingCategory(integrationId);
      try {
        await connect(integrationId);
      } finally {
        setConnectingCategory(null);
      }
    },
    [connect, connectingCategory],
  );

  const handleClose = useCallback(() => {
    setIsOpen(false);
  }, []);

  const handleSelectCategory = useCallback((category: string) => {
    void haptics.selection();
    setSelectedCategory(category);
  }, []);

  const allCategories = useMemo(() => ["all", ...categories], [categories]);

  const renderItem = useCallback(
    ({ item }: { item: ListItem }) => {
      if (item.type === "tool") {
        const tool = item.tool;
        return (
          <Pressable
            onPress={() => handleSelect(tool)}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              paddingHorizontal: 8,
              paddingVertical: 8,
              marginBottom: 2,
              borderRadius: 12,
              backgroundColor: pressed ? ROW_BG_PRESSED : "transparent",
            })}
            android_ripple={{ color: "rgba(255,255,255,0.06)" }}
          >
            <View style={{ marginRight: 8 }}>
              {getToolCategoryIcon(
                tool.category,
                {
                  size: 20,
                  showBackground: true,
                  pulsating: false,
                },
                tool.icon_url,
              )}
            </View>

            <View style={{ flex: 1, marginRight: spacing.sm }}>
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: ZINC_200,
                  fontWeight: "500",
                }}
                numberOfLines={1}
              >
                {formatToolName(tool.name)}
              </Text>
            </View>
          </Pressable>
        );
      }

      if (item.type === "locked-section") {
        const isConnecting = item.isConnecting;
        return (
          <View
            style={{
              marginTop: spacing.md,
              marginBottom: spacing.xs,
              backgroundColor: SECTION_BG,
              borderRadius: 12,
              padding: 8,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 12,
                flex: 1,
              }}
            >
              <View
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 8,
                  backgroundColor: RED_TILE_BG,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <AppIcon icon={ShieldUserIcon} size={16} color={RED_400} />
              </View>
              <View style={{ flex: 1 }}>
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: ZINC_200,
                    fontWeight: "500",
                  }}
                  numberOfLines={1}
                >
                  {item.tools.length} {item.categoryDisplayName} tools locked
                </Text>
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: ZINC_500,
                    marginTop: 1,
                  }}
                  numberOfLines={1}
                >
                  Requires {item.categoryDisplayName} connection
                </Text>
              </View>
            </View>

            {!item.isConnected && (
              <Pressable
                onPress={() => handleConnect(item.category)}
                disabled={isConnecting}
                style={({ pressed }) => ({
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  paddingHorizontal: 12,
                  paddingVertical: 6,
                  borderRadius: 999,
                  opacity: isConnecting ? 0.85 : 1,
                  backgroundColor: pressed
                    ? PRIMARY_CHIP_BG_PRESSED
                    : PRIMARY_CHIP_BG,
                })}
              >
                {isConnecting ? (
                  <Spinner size="sm" color="default" />
                ) : (
                  (getToolCategoryIcon(
                    item.category,
                    {
                      size: 14,
                      showBackground: false,
                    },
                    item.iconUrl,
                  ) ?? <AppIcon icon={ConnectIcon} size={14} color={PRIMARY} />)
                )}
                <Text
                  style={{
                    fontSize: 13,
                    fontWeight: "600",
                    color: PRIMARY,
                  }}
                >
                  {isConnecting ? "Connecting..." : "Connect"}
                </Text>
              </Pressable>
            )}
          </View>
        );
      }

      // locked tool — web mirrors LockedToolItem.tsx: blurred icon + name +
      // shield + category pill. We keep the pill on locked rows (helps users
      // know which integration to connect) but drop it on unlocked rows.
      const tool = item.tool;
      return (
        <Pressable
          onPress={() => handleConnect(tool.category)}
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: 8,
            paddingVertical: 8,
            marginBottom: 2,
            borderRadius: 12,
            opacity: 0.55,
          }}
          android_ripple={{ color: "rgba(255,255,255,0.05)" }}
        >
          <View style={{ marginRight: 8 }}>
            {getToolCategoryIcon(
              tool.category,
              {
                size: 20,
                showBackground: true,
              },
              tool.icon_url,
            )}
          </View>

          <View style={{ flex: 1, marginRight: spacing.sm }}>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: ZINC_500,
                fontWeight: "500",
              }}
              numberOfLines={1}
            >
              {formatToolName(tool.name)}
            </Text>
          </View>

          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <AppIcon icon={ShieldUserIcon} size={13} color={ZINC_500} />
            <View
              style={{
                borderWidth: 1,
                borderColor: "rgba(63,63,70,0.9)",
                backgroundColor: "rgba(39,39,42,0.9)",
                paddingHorizontal: spacing.sm,
                paddingVertical: 2,
                borderRadius: 999,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: ZINC_500,
                  fontWeight: "500",
                }}
                numberOfLines={1}
              >
                {formatToolName(tool.display_name || tool.category)}
              </Text>
            </View>
          </View>
        </Pressable>
      );
    },
    [handleSelect, handleConnect, spacing, fontSize],
  );

  const keyExtractor = useCallback((item: ListItem, index: number) => {
    if (item.type === "tool") return `tool-${item.tool.name}`;
    if (item.type === "locked-tool") return `locked-${item.tool.name}`;
    return `section-${item.category}-${index}`;
  }, []);

  const hasQuery = searchQuery.trim().length > 0;

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={SHEET_SNAP_POINTS}
          enableDynamicSizing={false}
          enablePanDownToClose
          // Disable content-pan so the sheet only dismisses via the handle or
          // backdrop. This frees the chip-strip ScrollView to handle horizontal
          // gestures without competing with the sheet's vertical pan-gesture.
          enableContentPanningGesture={false}
          backgroundStyle={{ backgroundColor: SHEET_BACKGROUND }}
          handleIndicatorStyle={{
            backgroundColor: SHEET_HANDLE_COLOR,
            width: 36,
          }}
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
              paddingTop: spacing.xs,
              paddingBottom: spacing.sm,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.base,
                fontWeight: "600",
                color: "#ffffff",
              }}
            >
              Tools
            </Text>
            <Pressable
              onPress={handleClose}
              hitSlop={6}
              style={({ pressed }) => ({
                width: 32,
                height: 32,
                borderRadius: 16,
                backgroundColor: pressed
                  ? "rgba(63,63,70,0.85)"
                  : HEADER_CLOSE_BG,
                alignItems: "center",
                justifyContent: "center",
              })}
            >
              <AppIcon icon={Cancel01Icon} size={16} color={ZINC_400} />
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
                borderRadius: 999,
                paddingHorizontal: spacing.sm + 4,
                paddingVertical: moderateScale(8, 0.5),
                backgroundColor: SEARCH_BG,
              }}
            >
              <AppIcon icon={Search01Icon} size={16} color={ZINC_500} />
              <BottomSheetTextInput
                style={{
                  flex: 1,
                  marginLeft: spacing.sm,
                  color: "#ffffff",
                  fontSize: fontSize.sm,
                  padding: 0,
                }}
                placeholder="Search tools..."
                placeholderTextColor={ZINC_500}
                value={searchQuery}
                onChangeText={setSearchQuery}
              />
            </View>
          </View>

          {/* Category chip strip — regular RN ScrollView. The sheet itself
              has enableContentPanningGesture disabled so it only dismisses via
              handle or backdrop. With no parent gesture competing, horizontal
              scroll inside the strip works as expected. */}
          <View style={{ height: 44 }}>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
              directionalLockEnabled
              overScrollMode="never"
              contentContainerStyle={{
                paddingHorizontal: spacing.md,
                paddingVertical: 4,
                gap: 6,
                alignItems: "center",
              }}
            >
              {allCategories.map((category) => {
                const isActive = selectedCategory === category;
                return (
                  <Pressable
                    key={category}
                    onPress={() => handleSelectCategory(category)}
                    style={({ pressed }) => ({
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 6,
                      paddingHorizontal: 12,
                      paddingVertical: 6,
                      borderRadius: 999,
                      backgroundColor: isActive
                        ? CHIP_ACTIVE_BG
                        : pressed
                          ? "rgba(255,255,255,0.08)"
                          : CHIP_INACTIVE_BG,
                    })}
                  >
                    {category === "all" ? (
                      <AppIcon
                        icon={LayoutGridIcon}
                        size={14}
                        color={isActive ? "#ffffff" : ZINC_400}
                      />
                    ) : (
                      <View>
                        {getToolCategoryIcon(
                          category,
                          {
                            size: 14,
                            showBackground: false,
                          },
                          categoryDisplayMap[category]?.iconUrl,
                        )}
                      </View>
                    )}
                    <Text
                      style={{
                        fontSize: 13,
                        fontWeight: "500",
                        color: isActive ? "#ffffff" : ZINC_400,
                      }}
                      numberOfLines={1}
                    >
                      {category === "all"
                        ? "All"
                        : formatToolName(
                            categoryDisplayMap[category]?.displayName ||
                              category,
                          )}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>

          {/* Tool list */}
          {isLoading ? (
            <SkeletonList spacing={spacing} />
          ) : isError ? (
            <ErrorState
              onRetry={refetchTools}
              spacing={spacing}
              fontSize={fontSize}
            />
          ) : (
            <BottomSheetFlatList
              data={listItems}
              keyExtractor={keyExtractor}
              renderItem={renderItem}
              contentContainerStyle={{
                paddingTop: spacing.xs,
                paddingBottom: spacing.xl + 24,
                paddingHorizontal: spacing.sm,
              }}
              showsVerticalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
              ListEmptyComponent={
                <EmptyState hasQuery={hasQuery} spacing={spacing} />
              }
            />
          )}
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

SlashCommandSheet.displayName = "SlashCommandSheet";
