import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { Image as ExpoImage } from "expo-image";
import { useRef, useState } from "react";
import { ActivityIndicator, Pressable, TextInput, View } from "react-native";
import { AppIcon, Clock04Icon, PlayIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { WORKFLOW_COLORS } from "../constants/colors";
import { useWorkflowActions } from "../hooks/use-workflow-actions";
import type { TriggerConfig } from "../types/trigger-types";
import type { CreateWorkflowPayload, Workflow } from "../types/workflow-types";
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

interface CreateWorkflowModalProps {
  visible: boolean;
  onClose: () => void;
  onCreated: (workflow: Workflow) => void;
}

const DEFAULT_SCHEDULE_CONFIG: ScheduleConfig = {
  preset: "daily",
  hour: 9,
  minute: 0,
};

export function CreateWorkflowModal({
  visible,
  onClose,
  onCreated,
}: CreateWorkflowModalProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const { createWorkflow, isCreating, createError } = useWorkflowActions();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [prompt, setPrompt] = useState("");
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

  const resetState = () => {
    setTitle("");
    setDescription("");
    setPrompt("");
    setMode("manual");
    setScheduleConfig(DEFAULT_SCHEDULE_CONFIG);
    setSelectedTrigger(null);
    setTriggerConfig(null);
  };

  const buildTriggerConfig = (): CreateWorkflowPayload["trigger_config"] => {
    if (mode === "manual") {
      return {
        type: "manual",
        enabled: true,
        trigger_name: "Manual",
      };
    }
    if (mode === "schedule") {
      return {
        type: "schedule",
        enabled: true,
        trigger_name: "Schedule",
        cron_expression: toCronExpression(scheduleConfig),
      };
    }
    if (selectedTrigger && triggerConfig) {
      return {
        ...triggerConfig,
        type: "integration",
        enabled: true,
        trigger_name: selectedTrigger.id,
        trigger_slug: selectedTrigger.id,
        integration_id: selectedTrigger.requiresIntegration,
      };
    }
    return { type: "manual", enabled: true, trigger_name: "Manual" };
  };

  const handleCreate = async () => {
    if (!title.trim() || !prompt.trim()) return;

    const payload: CreateWorkflowPayload = {
      title: title.trim(),
      description: description.trim() || undefined,
      prompt: prompt.trim(),
      trigger_config: buildTriggerConfig(),
    };
    const workflow = await createWorkflow(payload);
    if (workflow) {
      resetState();
      onCreated(workflow);
    }
  };

  const handleDismiss = () => {
    resetState();
    onClose();
  };

  const canSubmit =
    title.trim().length > 0 &&
    prompt.trim().length > 0 &&
    (mode !== "trigger" || selectedTrigger !== null);

  const handleTriggerSelect = (trigger: TriggerOption) => {
    setSelectedTrigger(trigger);
  };

  const handleTriggerSave = (trigger: TriggerOption, config: TriggerConfig) => {
    setSelectedTrigger(trigger);
    setTriggerConfig(config);
  };

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
        if (!open) handleDismiss();
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
              Create Workflow
            </Text>

            <View style={{ gap: spacing.xs }}>
              <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
                Title *
              </Text>
              <TextInput
                style={inputStyle}
                placeholder="e.g. Daily email digest"
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
                Prompt / Instructions *
              </Text>
              <TextInput
                style={[
                  inputStyle,
                  {
                    minHeight: 100,
                    textAlignVertical: "top",
                  },
                ]}
                placeholder="Describe exactly what GAIA should do when this workflow runs..."
                placeholderTextColor="#555"
                value={prompt}
                onChangeText={setPrompt}
                multiline
                maxLength={5000}
              />
            </View>

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

            {createError ? (
              <Text style={{ fontSize: fontSize.xs, color: "#ef4444" }}>
                {createError}
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
                onPress={handleDismiss}
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
                  void handleCreate();
                }}
                disabled={!canSubmit || isCreating}
                style={({ pressed }) => ({
                  flex: 1,
                  height: 48,
                  borderRadius: moderateScale(12, 0.5),
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor:
                    canSubmit && !isCreating ? "#00bbff" : "#1f3540",
                  opacity: pressed ? 0.85 : 1,
                })}
              >
                {isCreating ? (
                  <ActivityIndicator size="small" color="#000" />
                ) : (
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: "700",
                      color: canSubmit ? "#000" : "#52525b",
                    }}
                  >
                    Create
                  </Text>
                )}
              </Pressable>
            </View>
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>

      <TriggerPickerSheet
        ref={triggerPickerRef}
        onSelect={handleTriggerSelect}
        onSaveConfig={handleTriggerSave}
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
        <Text
          style={{
            fontSize: fontSize.xs,
            color: WORKFLOW_COLORS.textZinc500,
          }}
          numberOfLines={1}
        >
          {selected.description}
        </Text>
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
