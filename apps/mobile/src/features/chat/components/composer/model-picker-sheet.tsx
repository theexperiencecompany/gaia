import {
  BottomSheetFlatList,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { Pressable, View } from "react-native";
import {
  AiChipIcon,
  AppIcon,
  Brain02Icon,
  Cancel01Icon,
  FlashIcon,
  Image02Icon,
  Search01Icon,
  Tick02Icon,
  ZapIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { ModelInfo } from "@/features/chat/api/models-api";
import {
  useCurrentModel,
  useModels,
  useSelectModel,
} from "@/features/chat/hooks/use-models";
import { selectionHaptic } from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

const MODEL_STORAGE_KEY = "gaia:selected_model_id";

type ModelCapabilityGroup = "Fast" | "Balanced" | "Powerful";

function resolveCapabilityGroup(model: ModelInfo): ModelCapabilityGroup {
  const name = model.name.toLowerCase();

  if (
    name.includes("flash") ||
    name.includes("mini") ||
    name.includes("haiku") ||
    name.includes("fast") ||
    name.includes("instant")
  ) {
    return "Fast";
  }

  if (
    name.includes("pro") ||
    name.includes("opus") ||
    name.includes("gpt-4o") ||
    name.includes("gpt-4") ||
    name.includes("turbo") ||
    name.includes("sonnet") ||
    name.includes("3.7") ||
    name.includes("3.5")
  ) {
    return "Powerful";
  }

  return "Balanced";
}

function hasVisionSupport(model: ModelInfo): boolean {
  const name = model.name.toLowerCase();
  const provider = (model.model_provider ?? "").toLowerCase();
  return (
    name.includes("vision") ||
    name.includes("4o") ||
    name.includes("gemini") ||
    name.includes("claude-3") ||
    provider.includes("openai") ||
    provider.includes("google") ||
    provider.includes("anthropic")
  );
}

function formatContextWindow(maxTokens: number): string {
  if (maxTokens >= 1_000_000) {
    return `${(maxTokens / 1_000_000).toFixed(0)}M ctx`;
  }
  if (maxTokens >= 1_000) {
    return `${(maxTokens / 1_000).toFixed(0)}K ctx`;
  }
  return `${maxTokens} ctx`;
}

const CAPABILITY_ORDER: ModelCapabilityGroup[] = [
  "Fast",
  "Balanced",
  "Powerful",
];

type CapabilityIconEntry = {
  icon: typeof FlashIcon;
  color: string;
};

const CAPABILITY_ICONS: Record<ModelCapabilityGroup, CapabilityIconEntry> = {
  Fast: { icon: FlashIcon, color: "#f59e0b" },
  Balanced: { icon: ZapIcon, color: "#00bbff" },
  Powerful: { icon: Brain02Icon, color: "#a78bfa" },
};

export interface ModelPickerSheetRef {
  open: () => void;
  close: () => void;
}

interface ModelPickerSheetProps {
  currentModelId?: string;
  onSelectModel?: (modelId: string) => void;
}

type FlatItem =
  | { type: "header"; group: ModelCapabilityGroup }
  | { type: "model"; model: ModelInfo };

export const ModelPickerSheet = forwardRef<
  ModelPickerSheetRef,
  ModelPickerSheetProps
>(({ currentModelId, onSelectModel }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const { spacing, fontSize, iconSize, moderateScale } = useResponsive();
  const [searchQuery, setSearchQuery] = useState("");

  const { data: models } = useModels();
  const currentModel = useCurrentModel();
  const { select: selectModel, isPending } = useSelectModel();

  const activeModelId = currentModelId ?? currentModel?.model_id;

  const snapPoints = useMemo(() => ["55%", "80%"], []);

  useImperativeHandle(ref, () => ({
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
  }));

  const filteredModels = useMemo(() => {
    if (!models) return [];
    if (!searchQuery.trim()) return models;
    const q = searchQuery.toLowerCase();
    return models.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        (m.model_provider ?? "").toLowerCase().includes(q) ||
        (m.description ?? "").toLowerCase().includes(q),
    );
  }, [models, searchQuery]);

  const flatItems = useMemo((): FlatItem[] => {
    const grouped: Record<ModelCapabilityGroup, ModelInfo[]> = {
      Fast: [],
      Balanced: [],
      Powerful: [],
    };

    for (const model of filteredModels) {
      grouped[resolveCapabilityGroup(model)].push(model);
    }

    const items: FlatItem[] = [];
    for (const group of CAPABILITY_ORDER) {
      const groupModels = grouped[group];
      if (groupModels.length > 0) {
        items.push({ type: "header", group });
        for (const model of groupModels) {
          items.push({ type: "model", model });
        }
      }
    }
    return items;
  }, [filteredModels]);

  const handleSelect = useCallback(
    (model: ModelInfo) => {
      if (isPending) return;
      selectionHaptic();
      selectModel(model.model_id);
      void AsyncStorage.setItem(MODEL_STORAGE_KEY, model.model_id);
      onSelectModel?.(model.model_id);
      setIsOpen(false);
    },
    [isPending, selectModel, onSelectModel],
  );

  const renderItem = useCallback(
    ({ item }: { item: FlatItem }) => {
      if (item.type === "header") {
        const capIcon = CAPABILITY_ICONS[item.group];
        return (
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              paddingHorizontal: spacing.md,
              paddingTop: spacing.sm,
              paddingBottom: spacing.xs,
            }}
          >
            <AppIcon icon={capIcon.icon} size={13} color={capIcon.color} />
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#8e8e93",
                fontWeight: "600",
                textTransform: "uppercase",
                letterSpacing: 0.7,
              }}
            >
              {item.group}
            </Text>
          </View>
        );
      }

      const { model } = item;
      const isSelected = model.model_id === activeModelId;
      const isFree = model.lowest_tier.toLowerCase() === "free";
      const supportsVision = hasVisionSupport(model);
      const contextText = formatContextWindow(model.max_tokens);
      const providerLabel = model.model_provider ?? "Unknown";

      return (
        <Pressable
          onPress={() => handleSelect(model)}
          style={({ pressed }) => ({
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingVertical: moderateScale(10, 0.5),
            marginHorizontal: spacing.xs,
            borderRadius: moderateScale(12, 0.5),
            backgroundColor: isSelected
              ? "rgba(0,187,255,0.08)"
              : pressed
                ? "rgba(255,255,255,0.04)"
                : "transparent",
            gap: spacing.sm,
          })}
        >
          {/* Provider icon background */}
          <View
            style={{
              width: moderateScale(36, 0.5),
              height: moderateScale(36, 0.5),
              borderRadius: moderateScale(10, 0.5),
              backgroundColor: isSelected
                ? "rgba(0,187,255,0.12)"
                : "rgba(255,255,255,0.06)",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AppIcon
              icon={AiChipIcon}
              size={18}
              color={isSelected ? "#00bbff" : "#71717a"}
            />
          </View>

          <View style={{ flex: 1, gap: 3 }}>
            {/* Name + badges row */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                flexWrap: "wrap",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  fontWeight: isSelected ? "600" : "500",
                  color: isSelected ? "#00bbff" : "#e4e4e7",
                }}
                numberOfLines={1}
              >
                {model.name}
              </Text>
              {model.is_default && (
                <View
                  style={{
                    paddingHorizontal: moderateScale(6, 0.5),
                    paddingVertical: 1,
                    borderRadius: 4,
                    backgroundColor: "rgba(52,199,89,0.15)",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs - 1,
                      color: "#34c759",
                      fontWeight: "600",
                    }}
                  >
                    Default
                  </Text>
                </View>
              )}
              {!isFree && (
                <View
                  style={{
                    paddingHorizontal: moderateScale(6, 0.5),
                    paddingVertical: 1,
                    borderRadius: 4,
                    backgroundColor: "rgba(255,179,0,0.15)",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs - 1,
                      color: "#ffb300",
                      fontWeight: "600",
                    }}
                  >
                    Pro
                  </Text>
                </View>
              )}
            </View>

            {/* Meta row: provider badge + context + vision */}
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
            >
              <View
                style={{
                  paddingHorizontal: moderateScale(5, 0.5),
                  paddingVertical: 1,
                  borderRadius: 4,
                  backgroundColor: "rgba(255,255,255,0.06)",
                }}
              >
                <Text style={{ fontSize: fontSize.xs - 1, color: "#a1a1aa" }}>
                  {providerLabel}
                </Text>
              </View>
              <Text style={{ fontSize: fontSize.xs - 1, color: "#52525b" }}>
                {contextText}
              </Text>
              {supportsVision && (
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 2,
                  }}
                >
                  <AppIcon icon={Image02Icon} size={10} color="#52525b" />
                  <Text style={{ fontSize: fontSize.xs - 1, color: "#52525b" }}>
                    Vision
                  </Text>
                </View>
              )}
            </View>
          </View>

          {isSelected ? (
            <AppIcon icon={Tick02Icon} size={iconSize.sm} color="#00bbff" />
          ) : null}
        </Pressable>
      );
    },
    [activeModelId, handleSelect, spacing, fontSize, iconSize, moderateScale],
  );

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={snapPoints}
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
              Select Model
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

          {/* Search input */}
          <View
            style={{
              marginHorizontal: spacing.md,
              marginBottom: spacing.sm,
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.xs,
              backgroundColor: "rgba(255,255,255,0.06)",
              borderRadius: moderateScale(10, 0.5),
              paddingHorizontal: spacing.sm,
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.08)",
            }}
          >
            <AppIcon icon={Search01Icon} size={15} color="#52525b" />
            <BottomSheetTextInput
              placeholder="Search models..."
              placeholderTextColor="#52525b"
              value={searchQuery}
              onChangeText={setSearchQuery}
              style={{
                flex: 1,
                paddingVertical: moderateScale(9, 0.5),
                fontSize: fontSize.sm,
                color: "#e4e4e7",
              }}
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="search"
            />
            {searchQuery.length > 0 && (
              <Pressable onPress={() => setSearchQuery("")}>
                <AppIcon icon={Cancel01Icon} size={14} color="#52525b" />
              </Pressable>
            )}
          </View>

          {/* Model list grouped by capability */}
          <BottomSheetFlatList
            data={flatItems}
            keyExtractor={(item: FlatItem) =>
              item.type === "header"
                ? `header-${item.group}`
                : item.model.model_id
            }
            renderItem={renderItem}
            contentContainerStyle={{
              paddingBottom: 32,
              paddingTop: spacing.xs,
            }}
            showsVerticalScrollIndicator={false}
            ListEmptyComponent={
              <View
                style={{
                  alignItems: "center",
                  paddingVertical: spacing.xl,
                  gap: spacing.sm,
                }}
              >
                <AppIcon icon={AiChipIcon} size={32} color="#3a3a3c" />
                <Text style={{ fontSize: fontSize.sm, color: "#52525b" }}>
                  No models found
                </Text>
              </View>
            }
          />
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

ModelPickerSheet.displayName = "ModelPickerSheet";
