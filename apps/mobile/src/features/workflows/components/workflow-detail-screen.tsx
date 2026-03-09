import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import {
  ArrowLeft01Icon,
  Delete01Icon,
  Edit02Icon,
  FlowCircleIcon,
  HugeiconsIcon,
  PlayIcon,
  ToggleOffIcon,
  ToggleOnIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { useWorkflowActions } from "../hooks/use-workflow-actions";
import type { Workflow } from "../types/workflow-types";
import { EditWorkflowModal } from "./edit-workflow-modal";
import { WorkflowExecutionHistory } from "./workflow-execution-history";

interface WorkflowDetailScreenProps {
  workflowId: string;
  workflow: Workflow | null;
  executions: ReturnType<
    typeof import("../hooks/use-workflow-detail").useWorkflowDetail
  >["executions"];
  isLoading: boolean;
  isLoadingExecutions: boolean;
  error: string | null;
  onBack: () => void;
  onDeleted: () => void;
  onUpdated: (workflow: Workflow) => void;
  onActivationToggled: (workflow: Workflow) => void;
}

export function WorkflowDetailScreen({
  workflow,
  executions,
  isLoading,
  isLoadingExecutions,
  error,
  onBack,
  onDeleted,
  onUpdated,
  onActivationToggled,
}: WorkflowDetailScreenProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const {
    toggleActivation,
    executeWorkflow,
    deleteWorkflow,
    isActivating,
    isExecuting,
    isDeleting,
    actionError,
  } = useWorkflowActions();
  const [showEdit, setShowEdit] = useState(false);
  const [executeStatus, setExecuteStatus] = useState<string | null>(null);

  const handleToggle = useCallback(async () => {
    if (!workflow) return;
    const updated = await toggleActivation(workflow);
    if (updated) onActivationToggled(updated);
  }, [workflow, toggleActivation, onActivationToggled]);

  const handleExecute = useCallback(async () => {
    if (!workflow) return;
    const result = await executeWorkflow(workflow.id);
    if (result) {
      setExecuteStatus("Execution started");
      setTimeout(() => setExecuteStatus(null), 3000);
    }
  }, [workflow, executeWorkflow]);

  const handleDelete = useCallback(() => {
    if (!workflow) return;
    Alert.alert(
      "Delete Workflow",
      `Are you sure you want to delete "${workflow.title}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            const ok = await deleteWorkflow(workflow.id);
            if (ok) onDeleted();
          },
        },
      ],
    );
  }, [workflow, deleteWorkflow, onDeleted]);

  if (isLoading) {
    return (
      <View style={{ flex: 1, backgroundColor: "#0b0c0f" }}>
        <View
          style={{
            paddingTop: spacing.xl * 2,
            paddingHorizontal: spacing.md,
            paddingBottom: spacing.md,
            borderBottomWidth: 1,
            borderBottomColor: "rgba(255,255,255,0.08)",
            flexDirection: "row",
            alignItems: "center",
          }}
        >
          <Pressable
            onPress={onBack}
            style={{
              width: 36,
              height: 36,
              borderRadius: 999,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(255,255,255,0.05)",
            }}
          >
            <HugeiconsIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
          </Pressable>
        </View>
        <View
          style={{ flex: 1, alignItems: "center", justifyContent: "center" }}
        >
          <ActivityIndicator size="large" color="#16c1ff" />
        </View>
      </View>
    );
  }

  if (error || !workflow) {
    return (
      <View style={{ flex: 1, backgroundColor: "#0b0c0f" }}>
        <View
          style={{
            paddingTop: spacing.xl * 2,
            paddingHorizontal: spacing.md,
            paddingBottom: spacing.md,
            borderBottomWidth: 1,
            borderBottomColor: "rgba(255,255,255,0.08)",
            flexDirection: "row",
            alignItems: "center",
          }}
        >
          <Pressable
            onPress={onBack}
            style={{
              width: 36,
              height: 36,
              borderRadius: 999,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(255,255,255,0.05)",
            }}
          >
            <HugeiconsIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
          </Pressable>
        </View>
        <View
          style={{
            flex: 1,
            alignItems: "center",
            justifyContent: "center",
            paddingHorizontal: spacing.xl,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#ef4444",
              textAlign: "center",
            }}
          >
            {error ?? "Workflow not found"}
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: "#0b0c0f" }}>
      {/* Header */}
      <View
        style={{
          paddingTop: spacing.xl * 2,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.08)",
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <Pressable
          onPress={onBack}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          <HugeiconsIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
        </Pressable>

        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "600",
            color: "#fff",
            flex: 1,
          }}
          numberOfLines={1}
        >
          {workflow.title}
        </Text>

        <Pressable
          onPress={() => setShowEdit(true)}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          <HugeiconsIcon icon={Edit02Icon} size={16} color="#aaa" />
        </Pressable>

        <Pressable
          onPress={handleDelete}
          disabled={isDeleting}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(239,68,68,0.12)",
          }}
        >
          {isDeleting ? (
            <ActivityIndicator size="small" color="#ef4444" />
          ) : (
            <HugeiconsIcon icon={Delete01Icon} size={16} color="#ef4444" />
          )}
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={{
          padding: spacing.md,
          gap: spacing.lg,
          paddingBottom: 40,
        }}
      >
        {/* Status + identity */}
        <View
          style={{
            borderRadius: moderateScale(16, 0.5),
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.08)",
            backgroundColor: "#14171c",
            padding: spacing.md,
            gap: spacing.md,
          }}
        >
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            <View
              style={{
                width: 40,
                height: 40,
                borderRadius: 12,
                backgroundColor: "rgba(22,193,255,0.12)",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <HugeiconsIcon icon={FlowCircleIcon} size={22} color="#16c1ff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#e8ebef",
                }}
              >
                {workflow.title}
              </Text>
              {workflow.description ? (
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#8a9099",
                    marginTop: 2,
                  }}
                >
                  {workflow.description}
                </Text>
              ) : null}
            </View>
          </View>

          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <View
              style={{
                borderRadius: 999,
                paddingHorizontal: spacing.sm,
                paddingVertical: 3,
                backgroundColor: workflow.activated
                  ? "rgba(22,193,255,0.15)"
                  : "rgba(255,255,255,0.07)",
                flexDirection: "row",
                alignItems: "center",
                gap: 4,
              }}
            >
              <View
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 999,
                  backgroundColor: workflow.activated ? "#16c1ff" : "#555",
                }}
              />
              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  color: workflow.activated ? "#9fe6ff" : "#666",
                }}
              >
                {workflow.activated ? "Active" : "Inactive"}
              </Text>
            </View>
            <View
              style={{
                borderRadius: 999,
                paddingHorizontal: spacing.sm,
                paddingVertical: 3,
                backgroundColor: "rgba(255,255,255,0.07)",
              }}
            >
              <Text style={{ fontSize: fontSize.xs - 1, color: "#666" }}>
                {workflow.trigger_config?.type ?? "manual"}
              </Text>
            </View>
          </View>
        </View>

        {/* Actions */}
        <View
          style={{
            flexDirection: "row",
            gap: spacing.sm,
          }}
        >
          <Pressable
            onPress={() => {
              void handleToggle();
            }}
            disabled={isActivating}
            style={{
              flex: 1,
              borderRadius: moderateScale(12, 0.5),
              paddingVertical: spacing.md,
              alignItems: "center",
              justifyContent: "center",
              flexDirection: "row",
              gap: spacing.xs,
              backgroundColor: workflow.activated
                ? "rgba(22,193,255,0.15)"
                : "rgba(255,255,255,0.07)",
            }}
          >
            {isActivating ? (
              <ActivityIndicator
                size="small"
                color={workflow.activated ? "#16c1ff" : "#aaa"}
              />
            ) : (
              <>
                <HugeiconsIcon
                  icon={workflow.activated ? ToggleOnIcon : ToggleOffIcon}
                  size={16}
                  color={workflow.activated ? "#16c1ff" : "#aaa"}
                />
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: workflow.activated ? "#9fe6ff" : "#aaa",
                  }}
                >
                  {workflow.activated ? "Deactivate" : "Activate"}
                </Text>
              </>
            )}
          </Pressable>

          <Pressable
            onPress={() => {
              void handleExecute();
            }}
            disabled={isExecuting}
            style={{
              flex: 1,
              borderRadius: moderateScale(12, 0.5),
              paddingVertical: spacing.md,
              alignItems: "center",
              justifyContent: "center",
              flexDirection: "row",
              gap: spacing.xs,
              backgroundColor: "rgba(34,197,94,0.15)",
            }}
          >
            {isExecuting ? (
              <ActivityIndicator size="small" color="#22c55e" />
            ) : (
              <>
                <HugeiconsIcon icon={PlayIcon} size={14} color="#22c55e" />
                <Text style={{ fontSize: fontSize.sm, color: "#22c55e" }}>
                  Run Now
                </Text>
              </>
            )}
          </Pressable>
        </View>

        {(executeStatus ?? actionError) ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: executeStatus ? "#22c55e" : "#ef4444",
              textAlign: "center",
            }}
          >
            {executeStatus ?? actionError}
          </Text>
        ) : null}

        {/* Prompt */}
        {workflow.prompt ? (
          <View style={{ gap: spacing.sm }}>
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#8a9099",
                textTransform: "uppercase",
                letterSpacing: 1.2,
              }}
            >
              Instructions
            </Text>
            <View
              style={{
                borderRadius: moderateScale(12, 0.5),
                backgroundColor: "#111318",
                padding: spacing.md,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#c0c6cf",
                  lineHeight: 20,
                }}
              >
                {workflow.prompt}
              </Text>
            </View>
          </View>
        ) : null}

        {/* Execution history */}
        <View style={{ gap: spacing.sm }}>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#8a9099",
              textTransform: "uppercase",
              letterSpacing: 1.2,
            }}
          >
            Recent Runs
          </Text>
          <WorkflowExecutionHistory
            executions={executions}
            isLoading={isLoadingExecutions}
          />
        </View>
      </ScrollView>

      <EditWorkflowModal
        visible={showEdit}
        workflow={workflow}
        onClose={() => setShowEdit(false)}
        onUpdated={(updated) => {
          setShowEdit(false);
          onUpdated(updated);
        }}
      />
    </View>
  );
}
