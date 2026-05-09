import * as Haptics from "expo-haptics";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, ScrollView, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { WORKFLOW_COLORS } from "../constants/colors";
import { WORKFLOW_TOAST_TIMEOUT_MS } from "../constants/timing";
import { useWorkflowActions } from "../hooks/use-workflow-actions";
import type { Workflow, WorkflowExecution } from "../types/workflow-types";
import { WorkflowDetailActions } from "./detail/WorkflowDetailActions";
import { WorkflowDetailHeader } from "./detail/WorkflowDetailHeader";
import { WorkflowDetailHero } from "./detail/WorkflowDetailHero";
import { WorkflowDetailSteps } from "./detail/WorkflowDetailSteps";
import {
  type WorkflowDetailTab,
  WorkflowDetailTabs,
} from "./detail/WorkflowDetailTabs";
import {
  WorkflowMoreMenuSheet,
  type WorkflowMoreMenuSheetRef,
} from "./detail/WorkflowMoreMenuSheet";
import { EditWorkflowModal } from "./edit-workflow-modal";
import {
  GeneratePromptSheet,
  type GeneratePromptSheetRef,
} from "./generate-prompt-sheet";
import {
  PublishWorkflowModal,
  type PublishWorkflowModalRef,
} from "./publish-workflow-modal";
import {
  RegenerateStepsSheet,
  type RegenerateStepsSheetRef,
} from "./regenerate-steps-sheet";
import { WorkflowExecutionHistory } from "./workflow-execution-history";
import { WorkflowDetailSkeleton } from "./workflow-skeletons";

interface WorkflowDetailScreenProps {
  workflowId: string;
  workflow: Workflow | null;
  executions: WorkflowExecution[];
  executionsTotal?: number;
  hasMoreExecutions?: boolean;
  isLoading: boolean;
  isLoadingExecutions: boolean;
  error: string | null;
  onBack: () => void;
  onDeleted: () => void;
  onUpdated: (workflow: Workflow) => void;
  onActivationToggled: (workflow: Workflow) => void;
  onLoadMoreExecutions?: () => void;
}

export function WorkflowDetailScreen({
  workflow,
  executions,
  executionsTotal,
  hasMoreExecutions,
  isLoading,
  isLoadingExecutions,
  error,
  onBack,
  onDeleted,
  onUpdated,
  onActivationToggled,
  onLoadMoreExecutions,
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
  const [activeTab, setActiveTab] = useState<WorkflowDetailTab>("steps");
  const [currentWorkflow, setCurrentWorkflow] = useState<Workflow | null>(
    workflow,
  );
  const executeStatusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  const regenerateSheetRef = useRef<RegenerateStepsSheetRef>(null);
  const generatePromptSheetRef = useRef<GeneratePromptSheetRef>(null);
  const publishModalRef = useRef<PublishWorkflowModalRef>(null);
  const moreMenuRef = useRef<WorkflowMoreMenuSheetRef>(null);

  const activeWorkflow = currentWorkflow ?? workflow;

  useEffect(() => {
    return () => {
      if (executeStatusTimeoutRef.current) {
        clearTimeout(executeStatusTimeoutRef.current);
      }
    };
  }, []);

  const handleToggle = useCallback(async () => {
    if (!activeWorkflow) return;
    // Optimistic flip — snapshot, apply, revert on failure.
    const snapshot = activeWorkflow;
    const optimistic: Workflow = {
      ...activeWorkflow,
      activated: !activeWorkflow.activated,
    };
    setCurrentWorkflow(optimistic);
    onActivationToggled(optimistic);

    const updated = await toggleActivation(activeWorkflow);
    if (updated) {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setCurrentWorkflow(updated);
      onActivationToggled(updated);
    } else {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      setCurrentWorkflow(snapshot);
      onActivationToggled(snapshot);
    }
  }, [activeWorkflow, toggleActivation, onActivationToggled]);

  const handleExecute = useCallback(async () => {
    if (!activeWorkflow) return;
    const result = await executeWorkflow(activeWorkflow.id);
    if (result) {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setExecuteStatus("Execution started");
      if (executeStatusTimeoutRef.current) {
        clearTimeout(executeStatusTimeoutRef.current);
      }
      executeStatusTimeoutRef.current = setTimeout(() => {
        executeStatusTimeoutRef.current = null;
        setExecuteStatus(null);
      }, WORKFLOW_TOAST_TIMEOUT_MS);
    } else {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
    }
  }, [activeWorkflow, executeWorkflow]);

  const handleDelete = useCallback(() => {
    if (!activeWorkflow) return;
    Alert.alert(
      "Delete Workflow",
      `Are you sure you want to delete "${activeWorkflow.title}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            const ok = await deleteWorkflow(activeWorkflow.id);
            if (ok) {
              void Haptics.notificationAsync(
                Haptics.NotificationFeedbackType.Success,
              );
              onDeleted();
            } else {
              void Haptics.notificationAsync(
                Haptics.NotificationFeedbackType.Warning,
              );
            }
          },
        },
      ],
    );
  }, [activeWorkflow, deleteWorkflow, onDeleted]);

  const handleMoreOptions = useCallback(() => {
    if (!activeWorkflow) return;
    void Haptics.selectionAsync();
    moreMenuRef.current?.open();
  }, [activeWorkflow]);

  if (isLoading) {
    return (
      <View style={{ flex: 1, backgroundColor: WORKFLOW_COLORS.screenBg }}>
        <WorkflowDetailHeader onBack={onBack} />
        <ScrollView
          contentContainerStyle={{
            padding: spacing.md,
            gap: spacing.lg,
            paddingBottom: 40,
          }}
        >
          <WorkflowDetailSkeleton />
        </ScrollView>
      </View>
    );
  }

  if (error || !activeWorkflow) {
    return (
      <View style={{ flex: 1, backgroundColor: WORKFLOW_COLORS.screenBg }}>
        <WorkflowDetailHeader onBack={onBack} />
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
              color: WORKFLOW_COLORS.dangerText,
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
    <View style={{ flex: 1, backgroundColor: WORKFLOW_COLORS.screenBg }}>
      <WorkflowDetailHeader
        title={activeWorkflow.title}
        onBack={onBack}
        onMore={handleMoreOptions}
        showMore
        isWorking={isDeleting}
      />

      <ScrollView
        contentContainerStyle={{
          padding: spacing.md,
          gap: spacing.lg,
          paddingBottom: 40,
        }}
      >
        <WorkflowDetailHero workflow={activeWorkflow} />

        <WorkflowDetailActions
          workflow={activeWorkflow}
          isActivating={isActivating}
          isExecuting={isExecuting}
          onToggleActivation={() => void handleToggle()}
          onExecute={() => void handleExecute()}
        />

        {executeStatus || actionError ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: executeStatus
                ? WORKFLOW_COLORS.successText
                : WORKFLOW_COLORS.dangerText,
              textAlign: "center",
            }}
          >
            {executeStatus ?? actionError}
          </Text>
        ) : null}

        {(() => {
          // Single source of truth: prefer prompt (richer) over description.
          // Skip description entirely when prompt is present so we never show
          // the same text twice across the detail screen.
          const instructions =
            activeWorkflow.prompt?.trim() ||
            activeWorkflow.description?.trim() ||
            "";
          if (!instructions) return null;
          return (
            <View style={{ gap: spacing.sm }}>
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: WORKFLOW_COLORS.textFaint,
                  textTransform: "uppercase",
                  letterSpacing: 1.2,
                  fontWeight: "600",
                }}
              >
                Instructions
              </Text>
              <View
                style={{
                  borderRadius: moderateScale(16, 0.5),
                  backgroundColor: WORKFLOW_COLORS.cardBg,
                  padding: spacing.md,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: WORKFLOW_COLORS.textBody,
                    lineHeight: 20,
                  }}
                >
                  {instructions}
                </Text>
              </View>
            </View>
          );
        })()}

        <View style={{ gap: spacing.md }}>
          <WorkflowDetailTabs
            activeTab={activeTab}
            onChange={setActiveTab}
            stepsCount={activeWorkflow.steps.length}
            historyCount={executionsTotal}
          />

          {activeTab === "steps" ? (
            <WorkflowDetailSteps steps={activeWorkflow.steps} />
          ) : (
            <WorkflowExecutionHistory
              executions={executions}
              isLoading={isLoadingExecutions}
              hasMore={hasMoreExecutions}
              total={executionsTotal}
              onLoadMore={onLoadMoreExecutions}
            />
          )}
        </View>
      </ScrollView>

      <EditWorkflowModal
        visible={showEdit}
        workflow={activeWorkflow}
        onClose={() => setShowEdit(false)}
        onUpdated={(updated) => {
          setShowEdit(false);
          setCurrentWorkflow(updated);
          onUpdated(updated);
        }}
      />

      <RegenerateStepsSheet
        ref={regenerateSheetRef}
        onRegenerated={(updated) => {
          setCurrentWorkflow(updated);
          onUpdated(updated);
        }}
      />

      <GeneratePromptSheet
        ref={generatePromptSheetRef}
        onPromptSelected={(prompt) => {
          if (!activeWorkflow) return;
          const updated: Workflow = { ...activeWorkflow, prompt };
          setCurrentWorkflow(updated);
          onUpdated(updated);
        }}
      />

      <PublishWorkflowModal
        ref={publishModalRef}
        onPublished={(updated) => {
          setCurrentWorkflow(updated);
          onUpdated(updated);
        }}
        onUnpublished={(updated) => {
          setCurrentWorkflow(updated);
          onUpdated(updated);
        }}
      />

      <WorkflowMoreMenuSheet
        ref={moreMenuRef}
        isPublished={activeWorkflow.is_public ?? false}
        onRegenerate={() => regenerateSheetRef.current?.open(activeWorkflow)}
        onGeneratePrompt={() =>
          generatePromptSheetRef.current?.open(activeWorkflow)
        }
        onTogglePublish={() => publishModalRef.current?.open(activeWorkflow)}
        onEdit={() => setShowEdit(true)}
        onDelete={handleDelete}
      />
    </View>
  );
}
