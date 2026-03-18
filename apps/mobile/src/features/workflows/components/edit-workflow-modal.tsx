import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { useWorkflowActions } from "../hooks/use-workflow-actions";
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
import { WorkflowStepsEditor } from "./workflow-steps-editor";

const INLINE_TRIGGER_OPTIONS = [
  { id: "manual", label: "Manual" },
  { id: "scheduled", label: "Scheduled" },
  { id: "gmail", label: "Gmail" },
  { id: "slack", label: "Slack" },
  { id: "google_calendar", label: "Google Calendar" },
  { id: "github", label: "GitHub" },
  { id: "linear", label: "Linear" },
  { id: "notion", label: "Notion" },
  { id: "google_sheets", label: "Google Sheets" },
  { id: "google_docs", label: "Google Docs" },
  { id: "asana", label: "Asana" },
  { id: "todoist", label: "Todoist" },
] as const;

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
  const [inlineTrigger, setInlineTrigger] = useState<string>("manual");
  const [scheduleConfig, setScheduleConfig] = useState<ScheduleConfig>(
    DEFAULT_SCHEDULE_CONFIG,
  );

  // Seed fields whenever a different workflow is loaded
  useEffect(() => {
    if (workflow) {
      setTitle(workflow.title);
      setDescription(workflow.description ?? "");
      setPrompt(workflow.prompt ?? "");
      setSteps(workflow.steps ?? []);
      setInlineTrigger(workflow.trigger_config?.type ?? "manual");
      setScheduleConfig(
        scheduleConfigFromCron(workflow.trigger_config?.cron_expression),
      );
    }
  }, [workflow]);

  const handleSave = async () => {
    if (!workflow || !title.trim()) return;

    const triggerConfig: UpdateWorkflowPayload["trigger_config"] = {
      type: inlineTrigger,
      enabled: workflow.activated,
      trigger_name:
        INLINE_TRIGGER_OPTIONS.find((t) => t.id === inlineTrigger)?.label ??
        inlineTrigger,
      ...(inlineTrigger === "scheduled"
        ? { cron_expression: toCronExpression(scheduleConfig) }
        : {}),
    };

    const payload: UpdateWorkflowPayload = {
      title: title.trim(),
      description: description.trim() || undefined,
      prompt: prompt.trim(),
      trigger_config: triggerConfig,
      steps: steps.map((s, i) => ({ ...s, order: i + 1 })),
    };
    const updated = await updateWorkflow(workflow.id, payload);
    if (updated) {
      onUpdated(updated);
    }
  };

  const canSubmit = title.trim().length > 0;

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

            {/* Steps editor */}
            <WorkflowStepsEditor steps={steps} onChange={setSteps} />

            {/* Trigger selector — horizontal scrollable chips */}
            <View style={{ gap: spacing.xs }}>
              <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
                Trigger
              </Text>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ gap: spacing.sm }}
                keyboardShouldPersistTaps="handled"
              >
                {INLINE_TRIGGER_OPTIONS.map((option) => {
                  const isSelected = inlineTrigger === option.id;
                  return (
                    <Pressable
                      key={option.id}
                      onPress={() => setInlineTrigger(option.id)}
                      style={{
                        paddingHorizontal: spacing.md,
                        paddingVertical: spacing.sm,
                        borderRadius: moderateScale(20, 0.5),
                        borderWidth: 1,
                        borderColor: isSelected ? "#00bbff" : "#3f3f46",
                        backgroundColor: isSelected ? "#00bbff20" : "#27272a",
                      }}
                    >
                      <Text
                        style={{
                          fontSize: fontSize.xs,
                          fontWeight: "500",
                          color: isSelected ? "#00bbff" : "#a1a1aa",
                        }}
                      >
                        {option.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </ScrollView>

              {/* Schedule builder — shown when scheduled trigger is selected */}
              {inlineTrigger === "scheduled" && (
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
                  backgroundColor:
                    canSubmit && !isUpdating ? "#00bbff" : "#333",
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
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
}
