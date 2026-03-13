import {
  BottomSheetFlatList,
  BottomSheetScrollView,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useState,
} from "react";
import { ActivityIndicator, Image, Pressable, View } from "react-native";
import { AppIcon, Clock01Icon, PlayIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { workflowApi } from "../api/workflow-api";
import type {
  TriggerConfig,
  TriggerFieldSchema,
  TriggerSchema,
} from "../types/trigger-types";
import type { FieldWithMeta } from "./dynamic-trigger-form";
import { DynamicTriggerForm } from "./dynamic-trigger-form";

// ---------------------------------------------------------------------------
// Static trigger display metadata (icon URLs, labels, categories)
// ---------------------------------------------------------------------------

interface StaticTriggerMeta {
  id: string;
  label: string;
  description: string;
  category: "basic" | "integration";
  iconUrl?: string;
  integrationId?: string;
}

const STATIC_TRIGGER_META: StaticTriggerMeta[] = [
  {
    id: "manual",
    label: "Manual",
    description: "Run on demand from chat or app",
    category: "basic",
  },
  {
    id: "schedule",
    label: "Scheduled",
    description: "Run on a time-based schedule",
    category: "basic",
  },
  {
    id: "gmail",
    label: "Gmail",
    description: "Triggers on Gmail events",
    category: "integration",
    integrationId: "gmail",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/120px-Gmail_icon_%282020%29.svg.png",
  },
  {
    id: "google_calendar",
    label: "Google Calendar",
    description: "Triggers on calendar events",
    category: "integration",
    integrationId: "google_calendar",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Calendar_icon_%282020%29.svg/120px-Google_Calendar_icon_%282020%29.svg.png",
  },
  {
    id: "github",
    label: "GitHub",
    description: "Triggers on GitHub events",
    category: "integration",
    integrationId: "github",
    iconUrl:
      "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
  },
  {
    id: "slack",
    label: "Slack",
    description: "Triggers on Slack messages",
    category: "integration",
    integrationId: "slack",
    iconUrl:
      "https://a.slack-edge.com/80588/marketing/img/meta/slack_hash_128.png",
  },
  {
    id: "notion",
    label: "Notion",
    description: "Triggers on Notion page changes",
    category: "integration",
    integrationId: "notion",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/4/45/Notion_app_logo.png",
  },
  {
    id: "linear",
    label: "Linear",
    description: "Triggers on Linear issues",
    category: "integration",
    integrationId: "linear",
  },
  {
    id: "todoist",
    label: "Todoist",
    description: "Triggers on Todoist tasks",
    category: "integration",
    integrationId: "todoist",
  },
  {
    id: "google_sheets",
    label: "Google Sheets",
    description: "Triggers on new rows",
    category: "integration",
    integrationId: "google_sheets",
    iconUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/3/30/Google_Sheets_logo_%282014-2020%29.svg/120px-Google_Sheets_logo_%282014-2020%29.svg.png",
  },
  {
    id: "asana",
    label: "Asana",
    description: "Triggers on Asana tasks",
    category: "integration",
    integrationId: "asana",
  },
  {
    id: "google_docs",
    label: "Google Docs",
    description: "Triggers on Google Docs events",
    category: "integration",
    integrationId: "google_docs",
  },
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface TriggerOption {
  id: string;
  label: string;
  description: string;
  category: "basic" | "integration";
  iconUrl?: string;
  requiresIntegration?: string;
}

export { STATIC_TRIGGER_META as TRIGGER_OPTIONS };

export interface TriggerPickerSheetRef {
  open: () => void;
  close: () => void;
}

interface TriggerPickerSheetProps {
  onSelect: (trigger: TriggerOption) => void;
  onSaveConfig?: (trigger: TriggerOption, config: TriggerConfig) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildDefaultConfig(slug: string): TriggerConfig {
  return { type: slug, enabled: true };
}
function getSchemaFieldsForSlug(
  slug: string,
  schemas: TriggerSchema[],
): FieldWithMeta[] {
  const match = schemas.find(
    (s) => s.slug === slug || s.integration_id === slug,
  );
  if (!match) return [];
  return Object.entries(match.config_schema).map(
    ([name, schema]: [string, TriggerFieldSchema]) => ({ name, schema }),
  );
}

function metaForSlug(slug: string): StaticTriggerMeta | undefined {
  return STATIC_TRIGGER_META.find(
    (m) =>
      m.id === slug || (m.integrationId && slug.startsWith(m.integrationId)),
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface TriggerRowProps {
  item: StaticTriggerMeta;
  onPress: () => void;
  spacing: ReturnType<typeof useResponsive>["spacing"];
  fontSize: ReturnType<typeof useResponsive>["fontSize"];
}

function TriggerRow({ item, onPress, spacing, fontSize }: TriggerRowProps) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.md,
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm + 4,
        backgroundColor: pressed ? "rgba(255,255,255,0.04)" : "transparent",
      })}
    >
      <View
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          backgroundColor: "#2c2c2e",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {item.iconUrl ? (
          <Image
            source={{ uri: item.iconUrl }}
            style={{ width: 22, height: 22 }}
            resizeMode="contain"
          />
        ) : item.id === "schedule" ? (
          <AppIcon icon={Clock01Icon} size={18} color="#a1a1aa" />
        ) : (
          <AppIcon icon={PlayIcon} size={18} color="#a1a1aa" />
        )}
      </View>
      <View style={{ flex: 1 }}>
        <Text
          style={{ fontSize: fontSize.sm, fontWeight: "500", color: "#fff" }}
        >
          {item.label}
        </Text>
        <Text
          style={{ fontSize: fontSize.xs, color: "#71717a" }}
          numberOfLines={1}
        >
          {item.description}
        </Text>
      </View>
      {item.category === "integration" ? (
        <View
          style={{
            paddingHorizontal: spacing.sm,
            paddingVertical: 2,
            backgroundColor: "#2c2c2e",
            borderRadius: 6,
          }}
        >
          <Text style={{ fontSize: fontSize.xs - 1, color: "#71717a" }}>
            Integration
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const TriggerPickerSheet = forwardRef<
  TriggerPickerSheetRef,
  TriggerPickerSheetProps
>(({ onSelect, onSaveConfig }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [schemas, setSchemas] = useState<TriggerSchema[]>([]);
  const [schemasLoading, setSchemasLoading] = useState(false);
  const [selectedMeta, setSelectedMeta] = useState<StaticTriggerMeta | null>(
    null,
  );
  const [triggerConfig, setTriggerConfig] = useState<TriggerConfig>({
    type: "manual",
    enabled: true,
  });

  const { spacing, fontSize, moderateScale } = useResponsive();

  // Fetch trigger schemas from backend
  const fetchSchemas = useCallback(async () => {
    if (schemasLoading || schemas.length > 0) return;
    setSchemasLoading(true);
    try {
      const result = await workflowApi.getTriggerSchemas();
      setSchemas(result);
    } catch {
      // Silently fall back to static metadata when schemas are unavailable
    } finally {
      setSchemasLoading(false);
    }
  }, [schemasLoading, schemas.length]);

  useEffect(() => {
    void fetchSchemas();
  }, [fetchSchemas]);

  useImperativeHandle(ref, () => ({
    open: () => {
      setSearch("");
      setSelectedMeta(null);
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const filtered = STATIC_TRIGGER_META.filter(
    (t) =>
      t.label.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase()),
  );

  const handleSelectMeta = (meta: StaticTriggerMeta) => {
    setSelectedMeta(meta);
    setTriggerConfig(buildDefaultConfig(meta.id));
    // Also notify parent immediately (for backwards-compat with onSelect)
    const legacyOption: TriggerOption = {
      id: meta.id,
      label: meta.label,
      description: meta.description,
      category: meta.category,
      iconUrl: meta.iconUrl,
      requiresIntegration: meta.integrationId,
    };
    onSelect(legacyOption);
  };

  const handleSave = () => {
    if (!selectedMeta) return;
    if (onSaveConfig) {
      const legacyOption: TriggerOption = {
        id: selectedMeta.id,
        label: selectedMeta.label,
        description: selectedMeta.description,
        category: selectedMeta.category,
        iconUrl: selectedMeta.iconUrl,
        requiresIntegration: selectedMeta.integrationId,
      };
      onSaveConfig(legacyOption, triggerConfig);
    }
    setIsOpen(false);
    setSelectedMeta(null);
  };

  const schemaFields = selectedMeta
    ? getSchemaFieldsForSlug(selectedMeta.id, schemas)
    : [];

  const renderListItem = ({ item }: { item: StaticTriggerMeta }) => (
    <TriggerRow
      item={item}
      onPress={() => handleSelectMeta(item)}
      spacing={spacing}
      fontSize={fontSize}
    />
  );

  // Config panel shown after a trigger is selected
  const renderConfigPanel = () => {
    if (!selectedMeta) return null;

    const hasSchemaFields = schemaFields.length > 0;
    const displayMeta = metaForSlug(selectedMeta.id) ?? selectedMeta;

    return (
      <BottomSheetScrollView
        contentContainerStyle={{
          paddingHorizontal: spacing.md,
          paddingBottom: 40,
          gap: spacing.md,
        }}
        keyboardShouldPersistTaps="handled"
      >
        {/* Header row */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
            paddingBottom: spacing.xs,
          }}
        >
          <Pressable
            onPress={() => setSelectedMeta(null)}
            hitSlop={8}
            style={{
              paddingHorizontal: spacing.sm,
              paddingVertical: spacing.xs,
              backgroundColor: "#2c2c2e",
              borderRadius: 8,
            }}
          >
            <Text style={{ fontSize: fontSize.xs, color: "#a1a1aa" }}>
              ← Back
            </Text>
          </Pressable>
          <View
            style={{
              flex: 1,
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            {displayMeta.iconUrl ? (
              <Image
                source={{ uri: displayMeta.iconUrl }}
                style={{ width: 20, height: 20 }}
                resizeMode="contain"
              />
            ) : null}
            <Text
              style={{
                fontSize: fontSize.md,
                fontWeight: "600",
                color: "#fff",
              }}
            >
              {displayMeta.label}
            </Text>
          </View>
        </View>

        <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
          {displayMeta.description}
        </Text>

        {schemasLoading ? (
          <View style={{ alignItems: "center", paddingVertical: spacing.lg }}>
            <ActivityIndicator size="small" color="#00bbff" />
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#52525b",
                marginTop: spacing.xs,
              }}
            >
              Loading configuration options…
            </Text>
          </View>
        ) : hasSchemaFields ? (
          <DynamicTriggerForm
            fields={schemaFields}
            config={triggerConfig}
            onChange={setTriggerConfig}
          />
        ) : (
          <View
            style={{
              backgroundColor: "#2c2c2e",
              borderRadius: moderateScale(10, 0.5),
              padding: spacing.md,
            }}
          >
            <Text style={{ fontSize: fontSize.sm, color: "#71717a" }}>
              No additional configuration required for this trigger.
            </Text>
          </View>
        )}

        <Pressable
          onPress={handleSave}
          style={({ pressed }) => ({
            borderRadius: moderateScale(12, 0.5),
            paddingVertical: spacing.md,
            alignItems: "center",
            backgroundColor: pressed ? "#0099dd" : "#00bbff",
            marginTop: spacing.sm,
          })}
        >
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#000",
            }}
          >
            Save trigger configuration
          </Text>
        </Pressable>
      </BottomSheetScrollView>
    );
  };

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["70%", "92%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#141414" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
        >
          {selectedMeta ? (
            renderConfigPanel()
          ) : (
            <>
              {" "}
              <View
                style={{
                  paddingHorizontal: spacing.md,
                  paddingBottom: spacing.sm,
                }}
              >
                <BottomSheetTextInput
                  value={search}
                  onChangeText={setSearch}
                  placeholder="Search triggers..."
                  placeholderTextColor="#52525b"
                  style={{
                    backgroundColor: "#2c2c2e",
                    borderRadius: 10,
                    paddingHorizontal: spacing.md,
                    paddingVertical: spacing.sm,
                    color: "#fff",
                    fontSize: fontSize.sm,
                  }}
                />
              </View>
              <BottomSheetFlatList
                data={filtered}
                keyExtractor={(item: StaticTriggerMeta) => item.id}
                renderItem={renderListItem}
                contentContainerStyle={{ paddingBottom: spacing.xl }}
              />
            </>
          )}{" "}
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

TriggerPickerSheet.displayName = "TriggerPickerSheet";
