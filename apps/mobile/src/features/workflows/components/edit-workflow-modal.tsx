import {
  BottomSheetBackdrop,
  type BottomSheetBackdropProps,
  BottomSheetModal,
  BottomSheetScrollView,
} from "@gorhom/bottom-sheet";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Pressable, TextInput, View } from "react-native";
import { AppIcon, ArrowRight01Icon, Clock01Icon, PlayIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useWorkflowActions } from "../hooks/use-workflow-actions";
import type { UpdateWorkflowPayload, Workflow } from "../types/workflow-types";
import {
  ScheduleBuilder,
  toCronExpression,
  type ScheduleConfig,
} from "./schedule-builder";
import {
  TriggerPickerSheet,
  TRIGGER_OPTIONS,
  type TriggerOption,
  type TriggerPickerSheetRef,
} from "./trigger-picker-sheet";

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

const MANUAL_TRIGGER = TRIGGER_OPTIONS[0];

function triggerOptionFromWorkflow(workflow: Workflow): TriggerOption {
  const type = workflow.trigger_config?.type ?? "manual";
  return (
    TRIGGER_OPTIONS.find((t) => t.id === type) ?? MANUAL_TRIGGER
  );
}

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
  const [selectedTrigger, setSelectedTrigger] =
    useState<TriggerOption>(MANUAL_TRIGGER);
  const [scheduleConfig, setScheduleConfig] = useState<ScheduleConfig>(
    DEFAULT_SCHEDULE_CONFIG,
  );
  const sheetRef = useRef<BottomSheetModal>(null);
  const triggerPickerRef = useRef<TriggerPickerSheetRef>(null);
  const snapPoints = useMemo(() => ["75%", "90%"], []);

  // Seed fields whenever a different workflow is loaded
  useEffect(() => {
    if (workflow) {
      setTitle(workflow.title);
      setDescription(workflow.description ?? "");
      setPrompt(workflow.prompt ?? "");
      setSelectedTrigger(triggerOptionFromWorkflow(workflow));
      setScheduleConfig(
        scheduleConfigFromCron(workflow.trigger_config?.cron_expression),
      );
    }
  }, [workflow]);

  useEffect(() => {
    if (visible) {
      sheetRef.current?.present();
    } else {
      sheetRef.current?.dismiss();
    }
  }, [visible]);

  const handleSave = async () => {
    if (!workflow || !title.trim()) return;

    const triggerConfig: UpdateWorkflowPayload["trigger_config"] = {
      type: selectedTrigger.id,
      enabled: workflow.activated,
      trigger_name: selectedTrigger.label,
      ...(selectedTrigger.requiresIntegration
        ? { integration_id: selectedTrigger.requiresIntegration }
        : {}),
      ...(selectedTrigger.id === "scheduled"
        ? { cron_expression: toCronExpression(scheduleConfig) }
        : {}),
    };

    const payload: UpdateWorkflowPayload = {
      title: title.trim(),
      description: description.trim() || undefined,
      prompt: prompt.trim(),
      trigger_config: triggerConfig,
    };
    const updated = await updateWorkflow(workflow.id, payload);
    if (updated) {
      onUpdated(updated);
    }
  };

  const renderBackdrop = useCallback(
    (props: BottomSheetBackdropProps) => (
      <BottomSheetBackdrop
        {...props}
        disappearsOnIndex={-1}
        appearsOnIndex={0}
        opacity={0.6}
      />
    ),
    [],
  );

  const canSubmit = title.trim().length > 0;

  return (
    <>
      <BottomSheetModal
        ref={sheetRef}
        snapPoints={snapPoints}
        enableDynamicSizing={false}
        enablePanDownToClose
        onDismiss={onClose}
        backdropComponent={renderBackdrop}
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
              style={{
                backgroundColor: "#1c1c1e",
                borderRadius: moderateScale(12, 0.5),
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.md,
                fontSize: fontSize.sm,
                color: "#fff",
              }}
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
              style={{
                backgroundColor: "#1c1c1e",
                borderRadius: moderateScale(12, 0.5),
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.md,
                fontSize: fontSize.sm,
                color: "#fff",
              }}
              placeholder="What does this workflow do?"
              placeholderTextColor="#555"
              value={description}
              onChangeText={setDescription}
              maxLength={300}
            />
          </View>

          <View style={{ gap: spacing.xs }}>
            <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
              Prompt / Instructions
            </Text>
            <TextInput
              style={{
                backgroundColor: "#1c1c1e",
                borderRadius: moderateScale(12, 0.5),
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.md,
                fontSize: fontSize.sm,
                color: "#fff",
                minHeight: 100,
                textAlignVertical: "top",
              }}
              placeholder="Instructions for GAIA..."
              placeholderTextColor="#555"
              value={prompt}
              onChangeText={setPrompt}
              multiline
              maxLength={5000}
            />
          </View>

          {/* Trigger selector */}
          <View style={{ gap: spacing.xs }}>
            <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
              Trigger
            </Text>
            <Pressable
              onPress={() => triggerPickerRef.current?.open()}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.sm,
                backgroundColor: pressed
                  ? "rgba(0,187,255,0.08)"
                  : "rgba(0,187,255,0.05)",
                borderWidth: 1,
                borderColor: "rgba(0,187,255,0.25)",
                borderRadius: moderateScale(12, 0.5),
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm + 4,
              })}
            >
              <View
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 8,
                  backgroundColor: "#2c2c2e",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {selectedTrigger.id === "scheduled" ? (
                  <AppIcon icon={Clock01Icon} size={16} color="#00bbff" />
                ) : (
                  <AppIcon icon={PlayIcon} size={16} color="#00bbff" />
                )}
              </View>
              <View style={{ flex: 1 }}>
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    fontWeight: "500",
                    color: "#fff",
                  }}
                >
                  {selectedTrigger.label}
                </Text>
                <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                  {selectedTrigger.description}
                </Text>
              </View>
              <AppIcon icon={ArrowRight01Icon} size={16} color="#52525b" />
            </Pressable>

            {/* Schedule builder — shown when scheduled trigger is selected */}
            {selectedTrigger.id === "scheduled" && (
              <View
                style={{
                  backgroundColor: "#1c1c1e",
                  borderRadius: moderateScale(12, 0.5),
                  padding: spacing.md,
                  marginTop: spacing.xs,
                }}
              >
                <ScheduleBuilder
                  value={scheduleConfig}
                  onChange={setScheduleConfig}
                />
              </View>
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
              gap: spacing.sm,
              marginTop: spacing.sm,
            }}
          >
            <Pressable
              onPress={onClose}
              style={{
                flex: 1,
                borderRadius: moderateScale(12, 0.5),
                paddingVertical: spacing.md,
                alignItems: "center",
                backgroundColor: "rgba(255,255,255,0.07)",
              }}
            >
              <Text style={{ fontSize: fontSize.sm, color: "#aaa" }}>
                Cancel
              </Text>
            </Pressable>
            <Pressable
              onPress={() => {
                void handleSave();
              }}
              disabled={!canSubmit || isUpdating}
              style={{
                flex: 2,
                borderRadius: moderateScale(12, 0.5),
                paddingVertical: spacing.md,
                alignItems: "center",
                backgroundColor: canSubmit && !isUpdating ? "#00bbff" : "#333",
              }}
            >
              {isUpdating ? (
                <ActivityIndicator size="small" color="#000" />
              ) : (
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    fontWeight: "600",
                    color: canSubmit ? "#000" : "#666",
                  }}
                >
                  Save
                </Text>
              )}
            </Pressable>
          </View>
        </BottomSheetScrollView>
      </BottomSheetModal>

      <TriggerPickerSheet
        ref={triggerPickerRef}
        onSelect={setSelectedTrigger}
      />
    </>
  );
}
