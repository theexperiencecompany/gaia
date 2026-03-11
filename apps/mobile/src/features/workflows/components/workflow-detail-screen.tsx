import { Button, Card, Chip, Tabs } from "heroui-native";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, ScrollView, View } from "react-native";
import {
  AppIcon,
  ArrowLeft01Icon,
  Delete01Icon,
  Edit02Icon,
  FlowCircleIcon,
  PlayIcon,
  ToggleOffIcon,
  ToggleOnIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { useResponsive } from "@/lib/responsive";
import { useWorkflowActions } from "../hooks/use-workflow-actions";
import type { Workflow, WorkflowExecution } from "../types/workflow-types";
import { EditWorkflowModal } from "./edit-workflow-modal";
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
      <Button
        variant="secondary"
        size="sm"
        isIconOnly
        onPress={onBack}
        style={{
          width: 36,
          height: 36,
          borderRadius: 999,
          backgroundColor: "rgba(255,255,255,0.05)",
        }}
      >
        <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
      </Button>

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

      {workflow && (
        <>
          <Button
            variant="secondary"
            size="sm"
            isIconOnly
            onPress={() => setShowEdit(true)}
            style={{
              width: 36,
              height: 36,
              borderRadius: 999,
              backgroundColor: "rgba(255,255,255,0.05)",
            }}
          >
            <AppIcon icon={Edit02Icon} size={16} color="#aaa" />
          </Button>

          <Button
            variant="danger-soft"
            size="sm"
            isIconOnly
            onPress={handleDelete}
            isDisabled={isDeleting}
            style={{
              width: 36,
              height: 36,
              borderRadius: 999,
              backgroundColor: "rgba(239,68,68,0.12)",
            }}
          >
            {isDeleting ? (
              <ActivityIndicator size="small" color="#ef4444" />
            ) : (
              <AppIcon icon={Delete01Icon} size={16} color="#ef4444" />
            )}
          </Button>
        </>
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

  if (error || !workflow) {
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
      {renderHeaderBar(workflow.title)}

      <ScrollView
        contentContainerStyle={{
          padding: spacing.md,
          gap: spacing.lg,
          paddingBottom: 40,
        }}
      >
        <Card
          variant="secondary"
          style={{
            borderRadius: moderateScale(16, 0.5),
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.08)",
            backgroundColor: "#171920",
          }}
        >
          <Card.Body
            style={{
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
                <Card.Title
                  style={{
                    fontSize: fontSize.base,
                    fontWeight: "600",
                    color: "#e8ebef",
                  }}
                >
                  {workflow.title}
                </Card.Title>
                {workflow.description ? (
                  <Card.Description
                    style={{
                      fontSize: fontSize.xs,
                      color: "#8e8e93",
                      marginTop: 2,
                      lineHeight: 16,
                    }}
                  >
                    {workflow.description}
                  </Card.Description>
                ) : null}
              </View>
            </View>

            <View
              style={{
                flexDirection: "row",
                gap: spacing.sm,
                flexWrap: "wrap",
              }}
            >
              <Chip
                size="sm"
                variant="soft"
                color={workflow.activated ? "accent" : "default"}
                style={{ minHeight: 28, paddingHorizontal: spacing.sm }}
              >
                <View
                  style={{ flexDirection: "row", alignItems: "center", gap: 5 }}
                >
                  <View
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 999,
                      backgroundColor: workflow.activated ? "#00bbff" : "#555",
                    }}
                  />
                  <Chip.Label
                    style={{
                      fontSize: fontSize.xs - 1,
                      color: workflow.activated ? "#7de4ff" : "#666",
                    }}
                  >
                    {workflow.activated ? "Active" : "Inactive"}
                  </Chip.Label>
                </View>
              </Chip>

              <Chip
                size="sm"
                variant="soft"
                color="default"
                style={{ minHeight: 28, paddingHorizontal: spacing.sm }}
              >
                <Chip.Label
                  style={{
                    fontSize: fontSize.xs - 1,
                    color: "#8e8e93",
                  }}
                >
                  {workflow.trigger_config?.type ?? "manual"}
                </Chip.Label>
              </Chip>

              {workflow.is_system_workflow && (
                <Chip
                  size="sm"
                  variant="soft"
                  color="accent"
                  style={{ minHeight: 28, paddingHorizontal: spacing.sm }}
                >
                  <Chip.Label
                    style={{
                      fontSize: fontSize.xs - 1,
                      color: "#00bbff",
                    }}
                  >
                    System
                  </Chip.Label>
                </Chip>
              )}
            </View>
          </Card.Body>
        </Card>

        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          <Button
            variant="secondary"
            onPress={() => {
              void handleToggle();
            }}
            isDisabled={isActivating}
            style={{
              flex: 1,
              borderRadius: moderateScale(12, 0.5),
              backgroundColor: workflow.activated
                ? "rgba(0,187,255,0.15)"
                : "rgba(255,255,255,0.07)",
            }}
          >
            {isActivating ? (
              <ActivityIndicator
                size="small"
                color={workflow.activated ? "#00bbff" : "#aaa"}
              />
            ) : (
              <View
                style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
              >
                <AppIcon
                  icon={workflow.activated ? ToggleOnIcon : ToggleOffIcon}
                  size={16}
                  color={workflow.activated ? "#00bbff" : "#aaa"}
                />
                <Button.Label
                  style={{
                    fontSize: fontSize.sm,
                    color: workflow.activated ? "#7de4ff" : "#aaa",
                  }}
                >
                  {workflow.activated ? "Deactivate" : "Activate"}
                </Button.Label>
              </View>
            )}
          </Button>

          <Button
            variant="secondary"
            onPress={() => {
              void handleExecute();
            }}
            isDisabled={isExecuting}
            style={{
              flex: 1,
              borderRadius: moderateScale(12, 0.5),
              backgroundColor: "rgba(34,197,94,0.15)",
            }}
          >
            {isExecuting ? (
              <ActivityIndicator size="small" color="#22c55e" />
            ) : (
              <View
                style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
              >
                <AppIcon icon={PlayIcon} size={14} color="#22c55e" />
                <Button.Label
                  style={{
                    fontSize: fontSize.sm,
                    color: "#22c55e",
                  }}
                >
                  Run Now
                </Button.Label>
              </View>
            )}
          </Button>
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

        {workflow.prompt ? (
          <Card
            variant="secondary"
            style={{
              borderRadius: moderateScale(12, 0.5),
              backgroundColor: "#171920",
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.06)",
            }}
          >
            <Card.Body
              style={{
                padding: spacing.md,
                gap: spacing.sm,
              }}
            >
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
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#c0c6cf",
                  lineHeight: 20,
                }}
              >
                {workflow.prompt}
              </Text>
            </Card.Body>
          </Card>
        ) : null}

        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as "steps" | "history")}
          variant="pill"
        >
          <Tabs.List
            style={{
              backgroundColor: "rgba(255,255,255,0.04)",
              borderRadius: moderateScale(12, 0.5),
              padding: 4,
            }}
          >
            {(["steps", "history"] as const).map((tab) => (
              <Tabs.Trigger
                key={tab}
                value={tab}
                style={{
                  flex: 1,
                  borderRadius: moderateScale(10, 0.5),
                }}
              >
                {({ isSelected }) => (
                  <View
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    <Tabs.Label
                      style={{
                        fontSize: fontSize.sm,
                        fontWeight: isSelected ? "600" : "400",
                        color: isSelected ? "#fff" : "#8e8e93",
                      }}
                    >
                      {tab === "steps" ? "Steps" : "History"}
                    </Tabs.Label>
                    {tab === "steps" && workflow.steps.length > 0 && (
                      <Chip
                        size="sm"
                        variant="soft"
                        color={isSelected ? "accent" : "default"}
                        style={{ minHeight: 20, paddingHorizontal: 6 }}
                      >
                        <Chip.Label
                          style={{
                            fontSize: fontSize.xs - 1,
                            color: isSelected ? "#00bbff" : "#8e8e93",
                          }}
                        >
                          {workflow.steps.length}
                        </Chip.Label>
                      </Chip>
                    )}
                  </View>
                )}
              </Tabs.Trigger>
            ))}
            <Tabs.Indicator
              style={{
                backgroundColor: "#171920",
                borderRadius: moderateScale(10, 0.5),
              }}
            />
          </Tabs.List>

          <Tabs.Content value="steps" style={{ paddingTop: spacing.md }}>
            <Card
              variant="secondary"
              style={{
                borderRadius: moderateScale(16, 0.5),
                backgroundColor: "#171920",
                borderWidth: 1,
                borderColor: "rgba(255,255,255,0.06)",
              }}
            >
              <Card.Body style={{ padding: spacing.md }}>
                <WorkflowStepsList steps={workflow.steps} />
              </Card.Body>
            </Card>
          </Tabs.Content>

          <Tabs.Content value="history" style={{ paddingTop: spacing.md }}>
            <Card
              variant="secondary"
              style={{
                borderRadius: moderateScale(16, 0.5),
                backgroundColor: "#171920",
                borderWidth: 1,
                borderColor: "rgba(255,255,255,0.06)",
              }}
            >
              <Card.Body style={{ padding: spacing.sm }}>
                <WorkflowExecutionHistory
                  executions={executions}
                  isLoading={isLoadingExecutions}
                  hasMore={hasMoreExecutions}
                  total={executionsTotal}
                  onLoadMore={onLoadMoreExecutions}
                />
              </Card.Body>
            </Card>
          </Tabs.Content>
        </Tabs>
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

              <View style={{ flex: 1, gap: spacing.xs, paddingTop: 4 }}>
                <Chip
                  size="sm"
                  variant="soft"
                  color="default"
                  style={{ alignSelf: "flex-start", paddingHorizontal: 8 }}
                >
                  <View
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 5,
                    }}
                  >
                    {iconElement}
                    <Chip.Label
                      style={{
                        fontSize: fontSize.xs - 1,
                        color: "#8e8e93",
                      }}
                    >
                      {categoryLabel}
                    </Chip.Label>
                  </View>
                </Chip>

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
