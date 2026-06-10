import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { Image as ExpoImage } from "expo-image";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, TextInput, View } from "react-native";
import { AppIcon, Clock04Icon, PlayIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { WORKFLOW_COLORS } from "../constants/colors";
import { useWorkflowActions } from "../hooks/use-workflow-actions";
import type { TriggerConfig } from "../types/trigger-types";
import type {
  UpdateWorkflowPayload,
  Workflow,
  WorkflowStep,
} from "../types/workflow-types";
import {
  ScheduleBuilder,
  type ScheduleConfig,
  toCronExpression,
} from "./schedule-builder";
import { type TriggerMode, TriggerModeTabs } from "./trigger-mode-tabs";
import {
  type TriggerOption,
  TriggerPickerSheet,
  type TriggerPickerSheetRef,
} from "./trigger-picker-sheet";
import { WorkflowStepsEditor } from "./workflow-steps-editor";

interface EditWorkflowModalProps {
  visible: boolean;
  workflow: Workflow | null;
  onClose: () => void;
  onUpdated: (workflow: Workflow) => void;
}

const DEFAULT_SCHEDULE_CONFIG: ScheduleConfig = {
  preset: "daily",
  hour: 9,
  minute: 0,
};

function scheduleConfigFromCron(cron: string | undefined): ScheduleConfig {
  if (!cron) return DEFAULT_SCHEDULE_CONFIG;

  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) {
    return { preset: "custom", customCron: cron };
  }

  const [minute, hour, dayOfMonth, , dayOfWeek] = parts;

  if (cron === "0 * * * *") {
    return { preset: "hourly" };
  }
  if (dayOfWeek !== "*" && dayOfMonth === "*") {
    return {
      preset: "weekly",
      hour: Number(hour),
      minute: Number(minute),
      dayOfWeek: Number(dayOfWeek),
    };
  }
  if (dayOfMonth !== "*" && dayOfWeek === "*") {
    return {
      preset: "monthly",
      hour: Number(hour),
      minute: Number(minute),
      dayOfMonth: Number(dayOfMonth),
    };
  }
  if (dayOfMonth === "*" && dayOfWeek === "*") {
    return {
      preset: "daily",
      hour: Number(hour),
      minute: Number(minute),
    };
  }

  return { preset: "custom", customCron: cron };
}

function modeFromTriggerType(type: string | undefined): TriggerMode {
  if (!type || type === "manual") return "manual";
  if (type === "schedule" || type === "scheduled") return "schedule";
  return "trigger";
}

interface RawTriggerConfig {
  type?: string;
  trigger_name?: string;
  trigger_slug?: string;
  integration_id?: string;
  cron_expression?: string;
}

function deriveSelectedTrigger(
  raw: RawTriggerConfig | undefined,
): TriggerOption | null {
  if (!raw) return null;
  const slug = raw.trigger_slug ?? raw.trigger_name;
  if (!slug) return null;
  return {
    id: slug,
    label: slug,
    description: "",
    category: "integration",
    requiresIntegration: raw.integration_id,
  };
}

export function EditWorkflowModal({
  visible,
  workflow,
  onClose,
  onUpdated,
}: EditWorkflowModalProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const { updateWorkflow, isUpdating, actionError } = useWorkflowActions();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [prompt, setPrompt] = useState("");
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [mode, setMode] = useState<TriggerMode>("manual");
  const [scheduleConfig, setScheduleConfig] = useState<ScheduleConfig>(
    DEFAULT_SCHEDULE_CONFIG,
  );
  const [selectedTrigger, setSelectedTrigger] = useState<TriggerOption | null>(
    null,
  );
  const [triggerConfig, setTriggerConfig] = useState<TriggerConfig | null>(
    null,
  );
  const triggerPickerRef = useRef<TriggerPickerSheetRef>(null);

  // Seed fields whenever a different workflow is loaded
  useEffect(() => {
    if (workflow) {
      setTitle(workflow.title);
      setDescription(workflow.description ?? "");
      setPrompt(workflow.prompt ?? "");
      setSteps(workflow.steps ?? []);
      const triggerType = workflow.trigger_config?.type;
      setMode(modeFromTriggerType(triggerType));
      setScheduleConfig(
        scheduleConfigFromCron(workflow.trigger_config?.cron_expression),
      );
      if (
        triggerType &&
        triggerType !== "manual" &&
        triggerType !== "schedule" &&
        triggerType !== "scheduled"
      ) {
        const raw = workflow.trigger_config as unknown as RawTriggerConfig;
        setSelectedTrigger(deriveSelectedTrigger(raw));
        setTriggerConfig({
          ...(workflow.trigger_config as unknown as TriggerConfig),
          type: triggerType,
          enabled: workflow.activated,
        });
      } else {
        setSelectedTrigger(null);
        setTriggerConfig(null);
      }
    }
  }, [workflow]);

  const buildTriggerConfig = (): UpdateWorkflowPayload["trigger_config"] => {
    if (!workflow) return undefined;
    if (mode === "manual") {
      return {
        type: "manual",
        enabled: workflow.activated,
        trigger_name: "Manual",
      };
    }
    if (mode === "schedule") {
      return {
        type: "schedule",
        enabled: workflow.activated,
        trigger_name: "Schedule",
        cron_expression: toCronExpression(scheduleConfig),
      };
    }
    if (selectedTrigger && triggerConfig) {
      return {
        ...triggerConfig,
        type: "integration",
        enabled: workflow.activated,
        trigger_name: selectedTrigger.id,
        trigger_slug: selectedTrigger.id,
        integration_id: selectedTrigger.requiresIntegration,
      };
    }
    return {
      type: "manual",
      enabled: workflow.activated,
      trigger_name: "Manual",
    };
  };

  const handleSave = async () => {
    if (!workflow || !title.trim()) return;

    const payload: UpdateWorkflowPayload = {
      title: title.trim(),
      description: description.trim() || undefined,
      prompt: prompt.trim(),
      trigger_config: buildTriggerConfig(),
      steps: steps.map((s, i) => ({ ...s, order: i + 1 })),
    };
    const updated = await updateWorkflow(workflow.id, payload);
    if (updated) {
      onUpdated(updated);
    }
  };

  const canSubmit =
    title.trim().length > 0 && (mode !== "trigger" || selectedTrigger !== null);

  const inputStyle = {
    backgroundColor: "#1c1c1e",
    borderRadius: moderateScale(12, 0.5),
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    fontSize: fontSize.sm,
    color: "#fff",
  } as const;

  return (
    <BottomSheet
      isOpen={visible}
      onOpenChange={(open: boolean) => {
        if (!open) onClose();
      }}
    >
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["75%", "90%"]}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#141418" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
        >
          <BottomSheetScrollView
            contentContainerStyle={{
              paddingHorizontal: spacing.lg,
              paddingBottom: 40,
              gap: spacing.md,
            }}
            keyboardShouldPersistTaps="handled"
          >
            <Text
              style={{
                fontSize: fontSize.lg,
                fontWeight: "700",
                color: "#fff",
                marginBottom: spacing.xs,
              }}
            >
              Edit Workflow
            </Text>

            <View style={{ gap: spacing.xs }}>
              <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
                Title *
              </Text>
              <TextInput
                style={inputStyle}
                placeholder="Workflow title"
                placeholderTextColor="#555"
                value={title}
                onChangeText={setTitle}
                maxLength={100}
              />
            </View>

            <View style={{ gap: spacing.xs }}>
              <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
                Description
              </Text>
              <TextInput
                style={[
                  inputStyle,
                  {
                    minHeight: 72,
                    maxHeight: 160,
                    textAlignVertical: "top",
                    lineHeight: 20,
                  },
                ]}
                placeholder="What does this workflow do?"
                placeholderTextColor="#555"
                value={description}
                onChangeText={setDescription}
                multiline
                numberOfLines={3}
                maxLength={300}
              />
            </View>

            <View style={{ gap: spacing.xs }}>
              <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
                Prompt / Instructions
              </Text>
              <TextInput
                style={[
                  inputStyle,
                  { minHeight: 100, textAlignVertical: "top" },
                ]}
                placeholder="Instructions for GAIA..."
                placeholderTextColor="#555"
                value={prompt}
                onChangeText={setPrompt}
                multiline
                maxLength={5000}
              />
            </View>

            <WorkflowStepsEditor steps={steps} onChange={setSteps} />

            <View style={{ gap: spacing.sm }}>
              <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
                Trigger
              </Text>
              <TriggerModeTabs value={mode} onChange={setMode} />

              {mode === "manual" ? (
                <ManualPanel />
              ) : mode === "schedule" ? (
                <View
                  style={{
                    backgroundColor: "#1c1c1e",
                    borderRadius: moderateScale(12, 0.5),
                    padding: spacing.md,
                  }}
                >
                  <ScheduleBuilder
                    value={scheduleConfig}
                    onChange={setScheduleConfig}
                  />
                </View>
              ) : (
                <TriggerPanel
                  selected={selectedTrigger}
                  onPick={() => triggerPickerRef.current?.open()}
                />
              )}
            </View>

            {actionError ? (
              <Text style={{ fontSize: fontSize.xs, color: "#ef4444" }}>
                {actionError}
              </Text>
            ) : null}

            <View
              style={{
                flexDirection: "row",
                gap: 12,
                marginTop: spacing.sm,
              }}
            >
              <Pressable
                onPress={onClose}
                style={({ pressed }) => ({
                  flex: 1,
                  height: 48,
                  borderRadius: moderateScale(12, 0.5),
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor: "#3f3f46",
                  opacity: pressed ? 0.85 : 1,
                })}
              >
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    fontWeight: "600",
                    color: "#e4e4e7",
                  }}
                >
                  Cancel
                </Text>
              </Pressable>
              <Pressable
                onPress={() => {
                  void handleSave();
                }}
                disabled={!canSubmit || isUpdating}
                style={({ pressed }) => ({
                  flex: 1,
                  height: 48,
                  borderRadius: moderateScale(12, 0.5),
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor:
                    canSubmit && !isUpdating ? "#00bbff" : "#1f3540",
                  opacity: pressed ? 0.85 : 1,
                })}
              >
                {isUpdating ? (
                  <ActivityIndicator size="small" color="#000" />
                ) : (
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: "700",
                      color: canSubmit ? "#000" : "#52525b",
                    }}
                  >
                    Save
                  </Text>
                )}
              </Pressable>
            </View>
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>

      <TriggerPickerSheet
        ref={triggerPickerRef}
        onSelect={setSelectedTrigger}
        onSaveConfig={(trigger, config) => {
          setSelectedTrigger(trigger);
          setTriggerConfig(config);
        }}
      />
    </BottomSheet>
  );
}

function ManualPanel() {
  const { spacing, fontSize, moderateScale } = useResponsive();
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.md,
        backgroundColor: "#1c1c1e",
        borderRadius: moderateScale(12, 0.5),
        padding: spacing.md,
      }}
    >
      <View
        style={{
          width: 36,
          height: 36,
          borderRadius: 999,
          backgroundColor: WORKFLOW_COLORS.surfaceMuted,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon icon={PlayIcon} size={16} color={WORKFLOW_COLORS.primary} />
      </View>
      <View style={{ flex: 1 }}>
        <Text
          style={{
            fontSize: fontSize.sm,
            color: WORKFLOW_COLORS.textPrimary,
            fontWeight: "600",
          }}
        >
          Run on demand
        </Text>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: WORKFLOW_COLORS.textZinc500,
            marginTop: 2,
          }}
        >
          You decide exactly when to start this workflow.
        </Text>
      </View>
    </View>
  );
}

interface TriggerPanelProps {
  selected: TriggerOption | null;
  onPick: () => void;
}

function TriggerPanel({ selected, onPick }: TriggerPanelProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  if (!selected) {
    return (
      <Pressable
        onPress={onPick}
        style={({ pressed }) => ({
          backgroundColor: "#1c1c1e",
          borderRadius: moderateScale(12, 0.5),
          padding: spacing.md,
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
          opacity: pressed ? 0.85 : 1,
          minHeight: 80,
        })}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          <AppIcon
            icon={Clock04Icon}
            size={16}
            color={WORKFLOW_COLORS.primary}
          />
          <Text
            style={{
              fontSize: fontSize.sm,
              color: WORKFLOW_COLORS.primary,
              fontWeight: "600",
            }}
          >
            Choose a trigger
          </Text>
        </View>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: WORKFLOW_COLORS.textZinc500,
            textAlign: "center",
          }}
        >
          Run automatically when something happens in Gmail, Slack, GitHub,
          Linear, and more.
        </Text>
      </Pressable>
    );
  }

  return (
    <Pressable
      onPress={onPick}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.md,
        backgroundColor: "#1c1c1e",
        borderRadius: moderateScale(12, 0.5),
        padding: spacing.md,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <View
        style={{
          width: 36,
          height: 36,
          borderRadius: 999,
          backgroundColor: WORKFLOW_COLORS.surfaceMuted,
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        {selected.iconUrl ? (
          <ExpoImage
            source={{ uri: selected.iconUrl }}
            style={{ width: 22, height: 22 }}
            contentFit="contain"
          />
        ) : (
          <AppIcon
            icon={Clock04Icon}
            size={16}
            color={WORKFLOW_COLORS.textMuted}
          />
        )}
      </View>
      <View style={{ flex: 1 }}>
        <Text
          style={{
            fontSize: fontSize.sm,
            color: WORKFLOW_COLORS.textPrimary,
            fontWeight: "600",
          }}
          numberOfLines={1}
        >
          {selected.label}
        </Text>
        {selected.description ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: WORKFLOW_COLORS.textZinc500,
            }}
            numberOfLines={1}
          >
            {selected.description}
          </Text>
        ) : null}
      </View>
      <Text
        style={{
          fontSize: fontSize.xs,
          color: WORKFLOW_COLORS.primary,
          fontWeight: "600",
        }}
      >
        Change
      </Text>
    </Pressable>
  );
}
