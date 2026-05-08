import { getMobileIntegrationLogoUrl } from "@gaia/shared/icons";
import {
  BUILTIN_TRIGGER_META,
  type BuiltinTriggerMeta,
  buildDefaultTriggerConfig,
  formatIntegrationLabel,
  getSchemaFieldEntries,
  getTriggerLogoKey,
  groupTriggerSchemasByIntegration,
  type IntegrationTriggerGroup,
  type TriggerSchema,
} from "@gaia/shared/workflows";
import {
  BottomSheetFlatList,
  BottomSheetScrollView,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import { Image as ExpoImage } from "expo-image";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import {
  AppIcon,
  ArrowLeft01Icon,
  Clock01Icon,
  PlayIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { workflowApi } from "../api/workflow-api";
import { WORKFLOW_COLORS } from "../constants/colors";
import type { TriggerConfig } from "../types/trigger-types";
import type { FieldWithMeta } from "./dynamic-trigger-form";
import { DynamicTriggerForm } from "./dynamic-trigger-form";

// ---------------------------------------------------------------------------
// Public types kept for backwards-compat with create/edit modals
// ---------------------------------------------------------------------------

export interface TriggerOption {
  id: string;
  label: string;
  description: string;
  category: "basic" | "integration";
  iconUrl?: string;
  requiresIntegration?: string;
}

export interface TriggerPickerSheetRef {
  open: () => void;
  close: () => void;
}

interface TriggerPickerSheetProps {
  onSelect: (trigger: TriggerOption) => void;
  onSaveConfig?: (trigger: TriggerOption, config: TriggerConfig) => void;
}

// ---------------------------------------------------------------------------
// Internal step machine
// ---------------------------------------------------------------------------

type PickerStep =
  | { kind: "integrations" }
  | { kind: "subTriggers"; integrationId: string }
  | { kind: "config"; schema: TriggerSchema }
  | { kind: "config"; builtin: BuiltinTriggerMeta };

function logoUrlForIntegration(
  integrationId: string | undefined,
): string | undefined {
  if (!integrationId) return undefined;
  const key = getTriggerLogoKey(integrationId);
  return getMobileIntegrationLogoUrl(key) ?? undefined;
}

function builtinIcon(id: BuiltinTriggerMeta["id"]) {
  return id === "schedule" ? Clock01Icon : PlayIcon;
}

// ---------------------------------------------------------------------------
// Row renderers
// ---------------------------------------------------------------------------

interface RowProps {
  iconNode: React.ReactNode;
  title: string;
  subtitle?: string;
  trailingLabel?: string;
  onPress: () => void;
}

function Row({ iconNode, title, subtitle, trailingLabel, onPress }: RowProps) {
  const { spacing, fontSize } = useResponsive();
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
          backgroundColor: WORKFLOW_COLORS.surfaceMuted,
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        {iconNode}
      </View>
      <View style={{ flex: 1 }}>
        <Text
          style={{
            fontSize: fontSize.sm,
            fontWeight: "500",
            color: WORKFLOW_COLORS.textPrimary,
          }}
          numberOfLines={1}
        >
          {title}
        </Text>
        {subtitle ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: WORKFLOW_COLORS.textZinc500,
            }}
            numberOfLines={2}
          >
            {subtitle}
          </Text>
        ) : null}
      </View>
      {trailingLabel ? (
        <View
          style={{
            paddingHorizontal: spacing.sm,
            paddingVertical: 2,
            backgroundColor: WORKFLOW_COLORS.surfaceMuted,
            borderRadius: 6,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.xs - 1,
              color: WORKFLOW_COLORS.textZinc500,
            }}
          >
            {trailingLabel}
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}

interface BackHeaderProps {
  onBack: () => void;
  title: string;
  iconUrl?: string;
}

function BackHeader({ onBack, title, iconUrl }: BackHeaderProps) {
  const { spacing, fontSize } = useResponsive();
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.sm,
        paddingHorizontal: spacing.md,
        paddingBottom: spacing.xs,
      }}
    >
      <Pressable
        onPress={onBack}
        hitSlop={8}
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 4,
          paddingHorizontal: spacing.sm,
          paddingVertical: spacing.xs,
          backgroundColor: WORKFLOW_COLORS.surfaceMuted,
          borderRadius: 8,
        }}
      >
        <AppIcon
          icon={ArrowLeft01Icon}
          size={12}
          color={WORKFLOW_COLORS.textMuted}
        />
        <Text
          style={{
            fontSize: fontSize.xs,
            color: WORKFLOW_COLORS.textMuted,
            fontWeight: "600",
          }}
        >
          Back
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
        {iconUrl ? (
          <ExpoImage
            source={{ uri: iconUrl }}
            style={{ width: 20, height: 20 }}
            contentFit="contain"
          />
        ) : null}
        <Text
          style={{
            fontSize: fontSize.md,
            fontWeight: "600",
            color: WORKFLOW_COLORS.textPrimary,
          }}
          numberOfLines={1}
        >
          {title}
        </Text>
      </View>
    </View>
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
  const [step, setStep] = useState<PickerStep>({ kind: "integrations" });
  const [triggerConfig, setTriggerConfig] = useState<TriggerConfig>({
    type: "manual",
    enabled: true,
  });

  const { spacing, fontSize, moderateScale } = useResponsive();

  const fetchSchemas = useCallback(async () => {
    if (schemasLoading || schemas.length > 0) return;
    setSchemasLoading(true);
    try {
      const result = await workflowApi.getTriggerSchemas();
      setSchemas(result);
    } catch {
      // Silent: fall back to built-in triggers only.
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
      setStep({ kind: "integrations" });
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const groupedIntegrations: IntegrationTriggerGroup[] = useMemo(
    () => groupTriggerSchemasByIntegration(schemas),
    [schemas],
  );

  const filteredBuiltins = useMemo(() => {
    if (!search.trim()) return BUILTIN_TRIGGER_META;
    const q = search.toLowerCase();
    return BUILTIN_TRIGGER_META.filter(
      (t) =>
        t.label.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q),
    );
  }, [search]);

  const filteredIntegrations = useMemo(() => {
    if (!search.trim()) return groupedIntegrations;
    const q = search.toLowerCase();
    return groupedIntegrations.filter((group) => {
      const label = formatIntegrationLabel(group.integrationId).toLowerCase();
      if (label.includes(q)) return true;
      return group.schemas.some(
        (schema) =>
          schema.name.toLowerCase().includes(q) ||
          schema.description.toLowerCase().includes(q),
      );
    });
  }, [groupedIntegrations, search]);

  // ---- Step transitions ----

  const handlePickBuiltin = (builtin: BuiltinTriggerMeta) => {
    setTriggerConfig(buildDefaultTriggerConfig(builtin.id));
    onSelect({
      id: builtin.id,
      label: builtin.label,
      description: builtin.description,
      category: "basic",
    });
    setStep({ kind: "config", builtin });
  };

  const handlePickIntegration = (group: IntegrationTriggerGroup) => {
    if (group.schemas.length === 1) {
      // Skip the sub-trigger step when there's only one trigger for this
      // integration — go straight to its config.
      handlePickSchema(group.schemas[0]);
      return;
    }
    setStep({ kind: "subTriggers", integrationId: group.integrationId });
  };

  const handlePickSchema = (schema: TriggerSchema) => {
    setTriggerConfig(buildDefaultTriggerConfig(schema.slug));
    onSelect({
      id: schema.slug,
      label: schema.name,
      description: schema.description,
      category: "integration",
      iconUrl: logoUrlForIntegration(schema.integration_id),
      requiresIntegration: schema.integration_id,
    });
    setStep({ kind: "config", schema });
  };

  const handleSave = () => {
    if (!onSaveConfig || step.kind !== "config") {
      setIsOpen(false);
      return;
    }
    if ("builtin" in step) {
      onSaveConfig(
        {
          id: step.builtin.id,
          label: step.builtin.label,
          description: step.builtin.description,
          category: "basic",
        },
        triggerConfig,
      );
    } else {
      const schema = step.schema;
      onSaveConfig(
        {
          id: schema.slug,
          label: schema.name,
          description: schema.description,
          category: "integration",
          iconUrl: logoUrlForIntegration(schema.integration_id),
          requiresIntegration: schema.integration_id,
        },
        triggerConfig,
      );
    }
    setIsOpen(false);
    setStep({ kind: "integrations" });
  };

  // ---- Renderers per step ----

  type IntegrationsListItem =
    | { kind: "builtin"; meta: BuiltinTriggerMeta }
    | { kind: "integration"; group: IntegrationTriggerGroup };

  const renderIntegrationsStep = () => {
    const items: IntegrationsListItem[] = [
      ...filteredBuiltins.map(
        (meta): IntegrationsListItem => ({ kind: "builtin", meta }),
      ),
      ...filteredIntegrations.map(
        (group): IntegrationsListItem => ({ kind: "integration", group }),
      ),
    ];

    return (
      <>
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
            placeholderTextColor={WORKFLOW_COLORS.textMuted}
            style={{
              backgroundColor: WORKFLOW_COLORS.surfaceMuted,
              borderRadius: 10,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
              color: WORKFLOW_COLORS.textPrimary,
              fontSize: fontSize.sm,
            }}
          />
        </View>
        {schemasLoading && schemas.length === 0 ? (
          <View style={{ alignItems: "center", paddingVertical: spacing.xl }}>
            <ActivityIndicator size="small" color={WORKFLOW_COLORS.primary} />
            <Text
              style={{
                marginTop: spacing.xs,
                fontSize: fontSize.xs,
                color: WORKFLOW_COLORS.textMuted,
              }}
            >
              Loading triggers…
            </Text>
          </View>
        ) : (
          <BottomSheetFlatList
            data={items}
            keyExtractor={(item: IntegrationsListItem) =>
              item.kind === "builtin"
                ? `builtin:${item.meta.id}`
                : `integration:${item.group.integrationId}`
            }
            renderItem={({ item }: { item: IntegrationsListItem }) => {
              if (item.kind === "builtin") {
                return (
                  <Row
                    iconNode={
                      <AppIcon
                        icon={builtinIcon(item.meta.id)}
                        size={18}
                        color={WORKFLOW_COLORS.textMuted}
                      />
                    }
                    title={item.meta.label}
                    subtitle={item.meta.description}
                    onPress={() => handlePickBuiltin(item.meta)}
                  />
                );
              }
              const url = logoUrlForIntegration(item.group.integrationId);
              const subtitle =
                item.group.schemas.length === 1
                  ? item.group.schemas[0].description
                  : `${item.group.schemas.length} triggers`;
              return (
                <Row
                  iconNode={
                    url ? (
                      <ExpoImage
                        source={{ uri: url }}
                        style={{ width: 22, height: 22 }}
                        contentFit="contain"
                      />
                    ) : (
                      <AppIcon
                        icon={PlayIcon}
                        size={18}
                        color={WORKFLOW_COLORS.textMuted}
                      />
                    )
                  }
                  title={formatIntegrationLabel(item.group.integrationId)}
                  subtitle={subtitle}
                  trailingLabel="Integration"
                  onPress={() => handlePickIntegration(item.group)}
                />
              );
            }}
            contentContainerStyle={{ paddingBottom: spacing.xl }}
          />
        )}
      </>
    );
  };

  const renderSubTriggersStep = () => {
    if (step.kind !== "subTriggers") return null;
    const group = groupedIntegrations.find(
      (g) => g.integrationId === step.integrationId,
    );
    if (!group) return null;
    const url = logoUrlForIntegration(group.integrationId);
    return (
      <>
        <BackHeader
          onBack={() => setStep({ kind: "integrations" })}
          title={formatIntegrationLabel(group.integrationId)}
          iconUrl={url}
        />
        <BottomSheetFlatList
          data={group.schemas}
          keyExtractor={(item: TriggerSchema) => item.slug}
          renderItem={({ item }: { item: TriggerSchema }) => (
            <Row
              iconNode={
                url ? (
                  <ExpoImage
                    source={{ uri: url }}
                    style={{ width: 22, height: 22 }}
                    contentFit="contain"
                  />
                ) : (
                  <AppIcon
                    icon={PlayIcon}
                    size={18}
                    color={WORKFLOW_COLORS.textMuted}
                  />
                )
              }
              title={item.name}
              subtitle={item.description}
              onPress={() => handlePickSchema(item)}
            />
          )}
          contentContainerStyle={{ paddingBottom: spacing.xl }}
        />
      </>
    );
  };

  const renderConfigStep = () => {
    if (step.kind !== "config") return null;
    const isBuiltin = "builtin" in step;
    const titleLabel = isBuiltin ? step.builtin.label : step.schema.name;
    const description = isBuiltin
      ? step.builtin.description
      : step.schema.description;
    const url = isBuiltin
      ? undefined
      : logoUrlForIntegration(step.schema.integration_id);

    const onBack = () => {
      if (isBuiltin) {
        setStep({ kind: "integrations" });
      } else {
        const groupHasMultiple =
          groupedIntegrations.find(
            (g) => g.integrationId === step.schema.integration_id,
          )?.schemas.length ?? 0;
        if (groupHasMultiple > 1) {
          setStep({
            kind: "subTriggers",
            integrationId: step.schema.integration_id,
          });
        } else {
          setStep({ kind: "integrations" });
        }
      }
    };

    const fields: FieldWithMeta[] = isBuiltin
      ? []
      : getSchemaFieldEntries(step.schema);

    return (
      <BottomSheetScrollView
        contentContainerStyle={{
          paddingBottom: 40,
          gap: spacing.md,
        }}
        keyboardShouldPersistTaps="handled"
      >
        <BackHeader onBack={onBack} title={titleLabel} iconUrl={url} />

        <View style={{ paddingHorizontal: spacing.md, gap: spacing.md }}>
          {description ? (
            <Text
              style={{
                fontSize: fontSize.xs,
                color: WORKFLOW_COLORS.textZinc500,
              }}
            >
              {description}
            </Text>
          ) : null}

          {!isBuiltin && fields.length > 0 ? (
            <DynamicTriggerForm
              fields={fields}
              config={triggerConfig}
              onChange={setTriggerConfig}
              integrationId={step.schema.integration_id}
              triggerSlug={step.schema.slug}
            />
          ) : (
            <View
              style={{
                backgroundColor: WORKFLOW_COLORS.surfaceMuted,
                borderRadius: moderateScale(10, 0.5),
                padding: spacing.md,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: WORKFLOW_COLORS.textZinc500,
                }}
              >
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
              backgroundColor: pressed
                ? WORKFLOW_COLORS.primaryPressed
                : WORKFLOW_COLORS.primary,
              marginTop: spacing.sm,
            })}
          >
            <Text
              style={{
                fontSize: fontSize.sm,
                fontWeight: "600",
                color: WORKFLOW_COLORS.onPrimary,
              }}
            >
              Save trigger configuration
            </Text>
          </Pressable>
        </View>
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
          backgroundStyle={{ backgroundColor: WORKFLOW_COLORS.sheetBg }}
          handleIndicatorStyle={{
            backgroundColor: WORKFLOW_COLORS.handleIndicator,
            width: 40,
          }}
        >
          {step.kind === "integrations" && renderIntegrationsStep()}
          {step.kind === "subTriggers" && renderSubTriggersStep()}
          {step.kind === "config" && renderConfigStep()}
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

TriggerPickerSheet.displayName = "TriggerPickerSheet";
