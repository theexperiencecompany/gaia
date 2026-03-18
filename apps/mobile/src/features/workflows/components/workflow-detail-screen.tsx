import { useCallback, useRef, useState } from "react";
import {
  ActionSheetIOS,
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import {
  AppIcon,
  ArrowLeft01Icon,
  Delete01Icon,
  Edit02Icon,
  FlowCircleIcon,
  GlobeIcon,
  MagicWand01Icon,
  Menu01Icon,
  PlayIcon,
  RepeatIcon,
  ToggleOffIcon,
  ToggleOnIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { useResponsive } from "@/lib/responsive";
import { useWorkflowActions } from "../hooks/use-workflow-actions";
import type { Workflow, WorkflowExecution } from "../types/workflow-types";
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
  const [activeTab, setActiveTab] = useState<"steps" | "history">("steps");
  const [currentWorkflow, setCurrentWorkflow] = useState<Workflow | null>(
    workflow,
  );

  const regenerateSheetRef = useRef<RegenerateStepsSheetRef>(null);
  const generatePromptSheetRef = useRef<GeneratePromptSheetRef>(null);
  const publishModalRef = useRef<PublishWorkflowModalRef>(null);

  // Keep local workflow state in sync with prop
  const activeWorkflow = currentWorkflow ?? workflow;

  const handleToggle = useCallback(async () => {
    if (!activeWorkflow) return;
    const updated = await toggleActivation(activeWorkflow);
    if (updated) {
      setCurrentWorkflow(updated);
      onActivationToggled(updated);
    }
  }, [activeWorkflow, toggleActivation, onActivationToggled]);

  const handleExecute = useCallback(async () => {
    if (!activeWorkflow) return;
    const result = await executeWorkflow(activeWorkflow.id);
    if (result) {
      setExecuteStatus("Execution started");
      setTimeout(() => setExecuteStatus(null), 3000);
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
            if (ok) onDeleted();
          },
        },
      ],
    );
  }, [activeWorkflow, deleteWorkflow, onDeleted]);

  const handleMoreOptions = useCallback(() => {
    if (!activeWorkflow) return;

    const isPublished = activeWorkflow.is_public ?? false;
    const publishLabel = isPublished ? "Unpublish" : "Publish Workflow";

    const options = [
      "Regenerate Steps",
      "Generate Prompt",
      publishLabel,
      "Edit",
      "Delete",
      "Cancel",
    ];

    if (Platform.OS === "ios") {
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options,
          cancelButtonIndex: options.length - 1,
          destructiveButtonIndex: options.indexOf("Delete"),
        },
        (buttonIndex) => {
          switch (buttonIndex) {
            case 0:
              regenerateSheetRef.current?.open(activeWorkflow);
              break;
            case 1:
              generatePromptSheetRef.current?.open(activeWorkflow);
              break;
            case 2:
              publishModalRef.current?.open(activeWorkflow);
              break;
            case 3:
              setShowEdit(true);
              break;
            case 4:
              handleDelete();
              break;
          }
        },
      );
    } else {
      Alert.alert("Workflow Options", undefined, [
        {
          text: "Regenerate Steps",
          onPress: () => regenerateSheetRef.current?.open(activeWorkflow),
        },
        {
          text: "Generate Prompt",
          onPress: () => generatePromptSheetRef.current?.open(activeWorkflow),
        },
        {
          text: publishLabel,
          onPress: () => publishModalRef.current?.open(activeWorkflow),
        },
        { text: "Edit", onPress: () => setShowEdit(true) },
        {
          text: "Delete",
          style: "destructive",
          onPress: handleDelete,
        },
        { text: "Cancel", style: "cancel" },
      ]);
    }
  }, [activeWorkflow, handleDelete]);

  // Shared back button header
  const renderHeaderBar = (title?: string) => (
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
        <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
      </Pressable>

      {title ? (
        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "600",
            color: "#fff",
            flex: 1,
          }}
          numberOfLines={1}
        >
          {title}
        </Text>
      ) : (
        <View style={{ flex: 1 }} />
      )}

      {activeWorkflow && (
        <Pressable
          onPress={handleMoreOptions}
          disabled={isDeleting}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          {isDeleting ? (
            <ActivityIndicator size="small" color="#aaa" />
          ) : (
            <AppIcon icon={Menu01Icon} size={18} color="#aaa" />
          )}
        </Pressable>
      )}
    </View>
  );

  if (isLoading) {
    return (
      <View style={{ flex: 1, backgroundColor: "#131416" }}>
        {renderHeaderBar()}
        <View
          style={{ flex: 1, alignItems: "center", justifyContent: "center" }}
        >
          <ActivityIndicator size="large" color="#00bbff" />
        </View>
      </View>
    );
  }

  if (error || !activeWorkflow) {
    return (
      <View style={{ flex: 1, backgroundColor: "#131416" }}>
        {renderHeaderBar()}
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
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
      {renderHeaderBar(activeWorkflow.title)}

      <ScrollView
        contentContainerStyle={{
          padding: spacing.md,
          gap: spacing.lg,
          paddingBottom: 40,
        }}
      >
        {/* Identity card */}
        <View
          style={{
            borderRadius: moderateScale(16, 0.5),
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.08)",
            backgroundColor: "#171920",
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
                width: 44,
                height: 44,
                borderRadius: 12,
                backgroundColor: "rgba(0,187,255,0.12)",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <AppIcon icon={FlowCircleIcon} size={24} color="#00bbff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#e8ebef",
                }}
              >
                {activeWorkflow.title}
              </Text>
              {activeWorkflow.description ? (
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#8e8e93",
                    marginTop: 2,
                    lineHeight: 16,
                  }}
                >
                  {activeWorkflow.description}
                </Text>
              ) : null}
            </View>
          </View>

          {/* Status chips */}
          <View
            style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}
          >
            <View
              style={{
                borderRadius: 999,
                paddingHorizontal: spacing.sm,
                paddingVertical: 4,
                backgroundColor: activeWorkflow.activated
                  ? "rgba(0,187,255,0.15)"
                  : "rgba(255,255,255,0.07)",
                flexDirection: "row",
                alignItems: "center",
                gap: 5,
              }}
            >
              <View
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 999,
                  backgroundColor: activeWorkflow.activated
                    ? "#00bbff"
                    : "#555",
                }}
              />
              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  color: activeWorkflow.activated ? "#7de4ff" : "#666",
                }}
              >
                {activeWorkflow.activated ? "Active" : "Inactive"}
              </Text>
            </View>
            <View
              style={{
                borderRadius: 999,
                paddingHorizontal: spacing.sm,
                paddingVertical: 4,
                backgroundColor: "rgba(255,255,255,0.07)",
              }}
            >
              <Text style={{ fontSize: fontSize.xs - 1, color: "#8e8e93" }}>
                {activeWorkflow.trigger_config?.type ?? "manual"}
              </Text>
            </View>
            {activeWorkflow.is_public && (
              <View
                style={{
                  borderRadius: 999,
                  paddingHorizontal: spacing.sm,
                  paddingVertical: 4,
                  backgroundColor: "rgba(34,197,94,0.12)",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                <AppIcon icon={GlobeIcon} size={10} color="#22c55e" />
                <Text style={{ fontSize: fontSize.xs - 1, color: "#22c55e" }}>
                  Public
                </Text>
              </View>
            )}
            {activeWorkflow.is_system_workflow && (
              <View
                style={{
                  borderRadius: 999,
                  paddingHorizontal: spacing.sm,
                  paddingVertical: 4,
                  backgroundColor: "rgba(0,187,255,0.12)",
                }}
              >
                <Text style={{ fontSize: fontSize.xs - 1, color: "#00bbff" }}>
                  System
                </Text>
              </View>
            )}
          </View>
        </View>

        {/* Quick action chips row */}
        <View
          style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}
        >
          <Pressable
            onPress={() => regenerateSheetRef.current?.open(activeWorkflow)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              borderRadius: 999,
              paddingHorizontal: spacing.md,
              paddingVertical: 8,
              backgroundColor: "rgba(0,187,255,0.1)",
            }}
          >
            <AppIcon icon={RepeatIcon} size={13} color="#00bbff" />
            <Text style={{ fontSize: fontSize.xs, color: "#00bbff" }}>
              Regenerate Steps
            </Text>
          </Pressable>

          <Pressable
            onPress={() => generatePromptSheetRef.current?.open(activeWorkflow)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              borderRadius: 999,
              paddingHorizontal: spacing.md,
              paddingVertical: 8,
              backgroundColor: "rgba(167,139,250,0.1)",
            }}
          >
            <AppIcon icon={MagicWand01Icon} size={13} color="#a78bfa" />
            <Text style={{ fontSize: fontSize.xs, color: "#a78bfa" }}>
              Generate Prompt
            </Text>
          </Pressable>

          <Pressable
            onPress={() => publishModalRef.current?.open(activeWorkflow)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              borderRadius: 999,
              paddingHorizontal: spacing.md,
              paddingVertical: 8,
              backgroundColor: activeWorkflow.is_public
                ? "rgba(34,197,94,0.1)"
                : "rgba(255,255,255,0.07)",
            }}
          >
            <AppIcon
              icon={GlobeIcon}
              size={13}
              color={activeWorkflow.is_public ? "#22c55e" : "#8e8e93"}
            />
            <Text
              style={{
                fontSize: fontSize.xs,
                color: activeWorkflow.is_public ? "#22c55e" : "#8e8e93",
              }}
            >
              {activeWorkflow.is_public ? "Published" : "Publish"}
            </Text>
          </Pressable>
        </View>

        {/* Action buttons */}
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
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
              backgroundColor: activeWorkflow.activated
                ? "rgba(0,187,255,0.15)"
                : "rgba(255,255,255,0.07)",
            }}
          >
            {isActivating ? (
              <ActivityIndicator
                size="small"
                color={activeWorkflow.activated ? "#00bbff" : "#aaa"}
              />
            ) : (
              <>
                <AppIcon
                  icon={activeWorkflow.activated ? ToggleOnIcon : ToggleOffIcon}
                  size={16}
                  color={activeWorkflow.activated ? "#00bbff" : "#aaa"}
                />
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: activeWorkflow.activated ? "#7de4ff" : "#aaa",
                  }}
                >
                  {activeWorkflow.activated ? "Deactivate" : "Activate"}
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
                <AppIcon icon={PlayIcon} size={14} color="#22c55e" />
                <Text style={{ fontSize: fontSize.sm, color: "#22c55e" }}>
                  Run Now
                </Text>
              </>
            )}
          </Pressable>

          <Pressable
            onPress={() => setShowEdit(true)}
            style={{
              width: 44,
              borderRadius: moderateScale(12, 0.5),
              paddingVertical: spacing.md,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(255,255,255,0.07)",
            }}
          >
            <AppIcon icon={Edit02Icon} size={16} color="#aaa" />
          </Pressable>

          <Pressable
            onPress={handleDelete}
            disabled={isDeleting}
            style={{
              width: 44,
              borderRadius: moderateScale(12, 0.5),
              paddingVertical: spacing.md,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgba(239,68,68,0.12)",
            }}
          >
            {isDeleting ? (
              <ActivityIndicator size="small" color="#ef4444" />
            ) : (
              <AppIcon icon={Delete01Icon} size={16} color="#ef4444" />
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

        {/* Prompt / Instructions */}
        {activeWorkflow.prompt ? (
          <View style={{ gap: spacing.sm }}>
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#8e8e93",
                textTransform: "uppercase",
                letterSpacing: 1.2,
              }}
            >
              Instructions
            </Text>
            <View
              style={{
                borderRadius: moderateScale(12, 0.5),
                backgroundColor: "#171920",
                padding: spacing.md,
                borderWidth: 1,
                borderColor: "rgba(255,255,255,0.06)",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#c0c6cf",
                  lineHeight: 20,
                }}
              >
                {activeWorkflow.prompt}
              </Text>
            </View>
          </View>
        ) : null}

        {/* Steps & History tabs */}
        <View style={{ gap: spacing.md }}>
          {/* Tab bar */}
          <View
            style={{
              flexDirection: "row",
              gap: spacing.xs,
              backgroundColor: "rgba(255,255,255,0.04)",
              borderRadius: moderateScale(12, 0.5),
              padding: 4,
            }}
          >
            {(["steps", "history"] as const).map((tab) => (
              <Pressable
                key={tab}
                onPress={() => setActiveTab(tab)}
                style={{
                  flex: 1,
                  paddingVertical: 8,
                  borderRadius: moderateScale(10, 0.5),
                  alignItems: "center",
                  backgroundColor:
                    activeTab === tab ? "#171920" : "transparent",
                }}
              >
                <View
                  style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: activeTab === tab ? "600" : "400",
                      color: activeTab === tab ? "#fff" : "#8e8e93",
                    }}
                  >
                    {tab === "steps" ? "Steps" : "History"}
                  </Text>
                  {tab === "steps" && activeWorkflow.steps.length > 0 && (
                    <View
                      style={{
                        borderRadius: 999,
                        backgroundColor:
                          activeTab === "steps"
                            ? "rgba(0,187,255,0.2)"
                            : "rgba(255,255,255,0.1)",
                        paddingHorizontal: 6,
                        paddingVertical: 1,
                      }}
                    >
                      <Text
                        style={{
                          fontSize: fontSize.xs - 1,
                          color: activeTab === "steps" ? "#00bbff" : "#8e8e93",
                        }}
                      >
                        {activeWorkflow.steps.length}
                      </Text>
                    </View>
                  )}
                </View>
              </Pressable>
            ))}
          </View>

          {/* Tab content */}
          {activeTab === "steps" ? (
            <WorkflowStepsList steps={activeWorkflow.steps} />
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
    </View>
  );
}

function WorkflowStepsList({ steps }: { steps: Workflow["steps"] }) {
  const { spacing, fontSize } = useResponsive();

  if (steps.length === 0) {
    return (
      <View
        style={{
          paddingVertical: spacing.xl,
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <Text style={{ fontSize: fontSize.sm, color: "#71717a" }}>
          No steps generated yet
        </Text>
      </View>
    );
  }

  return (
    <View style={{ position: "relative", paddingBottom: spacing.lg }}>
      {/* Timeline line */}
      <View
        style={{
          position: "absolute",
          left: 13,
          top: 14,
          bottom: 20,
          width: 1,
          backgroundColor: "rgba(0,187,255,0.4)",
        }}
      />

      <View style={{ gap: spacing.xl }}>
        {steps.map((step, index) => {
          const categoryLabel =
            step.category === "gaia"
              ? "GAIA"
              : step.category
                  .replace(/_/g, " ")
                  .replace(/\b\w/g, (c) => c.toUpperCase());
          const iconElement = getToolCategoryIcon(step.category, {
            size: 14,
            showBackground: false,
          });

          return (
            <View
              key={step.id}
              style={{
                flexDirection: "row",
                alignItems: "flex-start",
                gap: spacing.md,
              }}
            >
              {/* Step number dot */}
              <View
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 999,
                  backgroundColor: "rgba(0,187,255,0.1)",
                  borderWidth: 1,
                  borderColor: "#00bbff",
                  alignItems: "center",
                  justifyContent: "center",
                  zIndex: 1,
                  flexShrink: 0,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    fontWeight: "600",
                    color: "#00bbff",
                  }}
                >
                  {index + 1}
                </Text>
              </View>

              {/* Step content */}
              <View style={{ flex: 1, gap: spacing.xs, paddingTop: 4 }}>
                {/* Category chip */}
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 5,
                    alignSelf: "flex-start",
                    borderRadius: 8,
                    paddingHorizontal: 8,
                    paddingVertical: 4,
                    backgroundColor: "rgba(255,255,255,0.06)",
                  }}
                >
                  {iconElement}
                  <Text
                    style={{
                      fontSize: fontSize.xs - 1,
                      color: "#8e8e93",
                    }}
                  >
                    {categoryLabel}
                  </Text>
                </View>

                <Text
                  style={{
                    fontSize: fontSize.sm,
                    fontWeight: "500",
                    color: "#e4e4e7",
                    lineHeight: 20,
                  }}
                >
                  {step.title}
                </Text>
                {step.description ? (
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      color: "#71717a",
                      lineHeight: 16,
                    }}
                  >
                    {step.description}
                  </Text>
                ) : null}
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}
