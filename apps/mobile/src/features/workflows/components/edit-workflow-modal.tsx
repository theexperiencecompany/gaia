import {
  BottomSheetBackdrop,
  type BottomSheetBackdropProps,
  BottomSheetModal,
  BottomSheetScrollView,
} from "@gorhom/bottom-sheet";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Pressable, TextInput, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useWorkflowActions } from "../hooks/use-workflow-actions";
import type { UpdateWorkflowPayload, Workflow } from "../types/workflow-types";

interface EditWorkflowModalProps {
  visible: boolean;
  workflow: Workflow | null;
  onClose: () => void;
  onUpdated: (workflow: Workflow) => void;
}

const TRIGGER_TYPES: { value: string; label: string; description: string }[] = [
  { value: "manual", label: "Manual", description: "Run on demand" },
  {
    value: "scheduled",
    label: "Scheduled",
    description: "Run on a schedule",
  },
];

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
  const [triggerType, setTriggerType] = useState("manual");
  const sheetRef = useRef<BottomSheetModal>(null);
  const snapPoints = useMemo(() => ["75%", "90%"], []);

  // Seed fields whenever a different workflow is loaded
  useEffect(() => {
    if (workflow) {
      setTitle(workflow.title);
      setDescription(workflow.description ?? "");
      setPrompt(workflow.prompt ?? "");
      setTriggerType(workflow.trigger_config?.type ?? "manual");
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
    const payload: UpdateWorkflowPayload = {
      title: title.trim(),
      description: description.trim() || undefined,
      prompt: prompt.trim(),
      trigger_config: { type: triggerType, enabled: workflow.activated },
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

        {/* Trigger type */}
        <View style={{ gap: spacing.xs }}>
          <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
            Trigger
          </Text>
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            {TRIGGER_TYPES.map(({ value, label, description: desc }) => {
              const isActive = triggerType === value;
              return (
                <Pressable
                  key={value}
                  onPress={() => setTriggerType(value)}
                  style={{
                    flex: 1,
                    borderRadius: moderateScale(12, 0.5),
                    paddingVertical: spacing.md,
                    paddingHorizontal: spacing.sm,
                    alignItems: "center",
                    backgroundColor: isActive
                      ? "rgba(0,187,255,0.15)"
                      : "#1c1c1e",
                    borderWidth: 1,
                    borderColor: isActive
                      ? "rgba(0,187,255,0.4)"
                      : "transparent",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: isActive ? "600" : "400",
                      color: isActive ? "#9fe6ff" : "#c5cad2",
                    }}
                  >
                    {label}
                  </Text>
                  <Text
                    style={{
                      fontSize: fontSize.xs - 1,
                      color: isActive ? "#6dd4f5" : "#555",
                      marginTop: 2,
                    }}
                  >
                    {desc}
                  </Text>
                </Pressable>
              );
            })}
          </View>
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
            <Text style={{ fontSize: fontSize.sm, color: "#aaa" }}>Cancel</Text>
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
  );
}
