import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { useState } from "react";
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
import type { CreateWorkflowPayload, Workflow } from "../types/workflow-types";
import {
  ScheduleBuilder,
  type ScheduleConfig,
  toCronExpression,
} from "./schedule-builder";

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
  const [inlineTrigger, setInlineTrigger] = useState<string>("manual");
  const [scheduleConfig, setScheduleConfig] = useState<ScheduleConfig>(
    DEFAULT_SCHEDULE_CONFIG,
  );

  const handleCreate = async () => {
    if (!title.trim() || !prompt.trim()) return;

    const triggerConfig: CreateWorkflowPayload["trigger_config"] = {
      type: inlineTrigger,
      enabled: true,
      trigger_name:
        INLINE_TRIGGER_OPTIONS.find((t) => t.id === inlineTrigger)?.label ??
        inlineTrigger,
      ...(inlineTrigger === "scheduled"
        ? { cron_expression: toCronExpression(scheduleConfig) }
        : {}),
    };

    const payload: CreateWorkflowPayload = {
      title: title.trim(),
      description: description.trim() || undefined,
      prompt: prompt.trim(),
      trigger_config: triggerConfig,
    };
    const workflow = await createWorkflow(payload);
    if (workflow) {
      setTitle("");
      setDescription("");
      setPrompt("");
      setInlineTrigger("manual");
      setScheduleConfig(DEFAULT_SCHEDULE_CONFIG);
      onCreated(workflow);
    }
  };

  const handleDismiss = () => {
    setTitle("");
    setDescription("");
    setPrompt("");
    setInlineTrigger("manual");
    setScheduleConfig(DEFAULT_SCHEDULE_CONFIG);
    onClose();
  };

  const canSubmit = title.trim().length > 0 && prompt.trim().length > 0;

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
                style={{
                  backgroundColor: "#1c1c1e",
                  borderRadius: moderateScale(12, 0.5),
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.md,
                  fontSize: fontSize.sm,
                  color: "#fff",
                }}
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
                Prompt / Instructions *
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
                placeholder="Describe exactly what GAIA should do when this workflow runs..."
                placeholderTextColor="#555"
                value={prompt}
                onChangeText={setPrompt}
                multiline
                maxLength={5000}
              />
            </View>

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

            {createError ? (
              <Text style={{ fontSize: fontSize.xs, color: "#ef4444" }}>
                {createError}
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
                onPress={handleDismiss}
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
                  void handleCreate();
                }}
                disabled={!canSubmit || isCreating}
                style={{
                  flex: 2,
                  borderRadius: moderateScale(12, 0.5),
                  paddingVertical: spacing.md,
                  alignItems: "center",
                  backgroundColor:
                    canSubmit && !isCreating ? "#00bbff" : "#333",
                }}
              >
                {isCreating ? (
                  <ActivityIndicator size="small" color="#000" />
                ) : (
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: "600",
                      color: canSubmit ? "#000" : "#666",
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
    </BottomSheet>
  );
}
