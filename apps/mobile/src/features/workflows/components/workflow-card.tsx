import { useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Modal, Pressable, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  Clock04Icon,
  Delete02Icon,
  GlobeIcon,
  PencilEdit02Icon,
  PlayIcon,
  Settings02Icon,
  ToggleOffIcon,
  ToggleOnIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { useResponsive } from "@/lib/responsive";
import { workflowApi } from "../api/workflow-api";
import type { Workflow } from "../types/workflow-types";
import { formatRunCount, getTriggerLabel } from "../utils/format-utils";

type ExecutionStatusDot = "success" | "failed" | "running" | "idle";

interface WorkflowCardProps {
  workflow: Workflow;
  onPress?: (workflow: Workflow) => void;
  onUpdated?: () => void;
}

export function WorkflowCard({
  workflow,
  onPress,
  onUpdated,
}: WorkflowCardProps) {
  const router = useRouter();
  const { spacing, fontSize, moderateScale } = useResponsive();
  const [menuVisible, setMenuVisible] = useState(false);
  const [runningStatus, setRunningStatus] =
    useState<ExecutionStatusDot>("idle");
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  const handlePress = () => {
    if (onPress) {
      onPress(workflow);
    } else {
      router.push(`/(app)/workflows/${workflow.id}`);
    }
  };

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (workflowId: string) => {
      stopPolling();
      pollingRef.current = setInterval(() => {
        workflowApi
          .getWorkflowStatus(workflowId)
          .then((statusResponse) => {
            const { status } = statusResponse;
            if (status === "success" || status === "completed") {
              setRunningStatus("success");
              stopPolling();
            } else if (status === "failed" || status === "error") {
              setRunningStatus("failed");
              stopPolling();
            }
          })
          .catch(() => {
            setRunningStatus("failed");
            stopPolling();
          });
      }, 2000);
    },
    [stopPolling],
  );

  const handleRun = useCallback(() => {
    setMenuVisible(false);
    setRunningStatus("running");
    workflowApi
      .executeWorkflow(workflow.id)
      .then(() => {
        startPolling(workflow.id);
      })
      .catch(() => {
        setRunningStatus("failed");
      });
  }, [workflow.id, startPolling]);

  const handleToggleActivation = useCallback(() => {
    setMenuVisible(false);
    const action = workflow.activated
      ? workflowApi.deactivateWorkflow(workflow.id)
      : workflowApi.activateWorkflow(workflow.id);
    action
      .then(() => {
        onUpdated?.();
      })
      .catch(() => {
        Alert.alert(
          "Error",
          `Failed to ${workflow.activated ? "deactivate" : "activate"} workflow`,
        );
      });
  }, [workflow.id, workflow.activated, onUpdated]);

  const handlePublish = useCallback(() => {
    setMenuVisible(false);
    const action = workflow.is_public
      ? workflowApi.unpublishWorkflow(workflow.id)
      : workflowApi.publishWorkflow(workflow.id);
    action
      .then(() => {
        onUpdated?.();
      })
      .catch(() => {
        Alert.alert(
          "Error",
          `Failed to ${workflow.is_public ? "unpublish" : "publish"} workflow`,
        );
      });
  }, [workflow.id, workflow.is_public, onUpdated]);

  const handleDelete = useCallback(() => {
    setMenuVisible(false);
    Alert.alert(
      "Delete Workflow",
      `Are you sure you want to delete "${workflow.title}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => {
            workflowApi
              .deleteWorkflow(workflow.id)
              .then(() => {
                onUpdated?.();
              })
              .catch(() => {
                Alert.alert("Error", "Failed to delete workflow");
              });
          },
        },
      ],
    );
  }, [workflow.id, workflow.title, onUpdated]);

  const triggerLabel = getTriggerLabel(
    workflow.trigger_config?.type ?? "manual",
  );
  const runCountText = formatRunCount(workflow.total_executions ?? 0);

  return (
    <>
      <Pressable
        onPress={handlePress}
        style={({ pressed }) => ({
          borderRadius: moderateScale(24, 0.5),
          backgroundColor: pressed ? "rgba(63,63,70,0.5)" : "rgba(39,39,42,1)",
          padding: spacing.md,
          gap: spacing.sm,
        })}
      >
        {/* Top row: step category icons + status chips + menu */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <WorkflowStepIcons steps={workflow.steps} />

          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <ExecutionStatusIndicator status={runningStatus} />
            <ActivationChip activated={workflow.activated} />

            <Pressable
              onPress={() => setMenuVisible(true)}
              hitSlop={8}
              style={{
                padding: 4,
                borderRadius: 8,
                backgroundColor: "rgba(255,255,255,0.06)",
              }}
            >
              <AppIcon icon={Settings02Icon} size={14} color="#71717a" />
            </Pressable>
          </View>
        </View>

        {/* Title */}
        <View>
          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "500",
              color: "#fff",
            }}
            numberOfLines={2}
          >
            {workflow.title}
          </Text>
          {workflow.description ? (
            <Text
              style={{
                fontSize: fontSize.xs,
                color: "#71717a",
                marginTop: 4,
                lineHeight: 16,
              }}
              numberOfLines={2}
            >
              {workflow.description}
            </Text>
          ) : null}
        </View>

        {/* Bottom row: trigger + run count */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: 2,
          }}
        >
          <View style={{ gap: 4 }}>
            {triggerLabel !== "Manual" && (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                <AppIcon icon={Clock04Icon} size={14} color="#71717a" />
                <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                  {triggerLabel}
                </Text>
              </View>
            )}

            {runCountText !== "Never run" && (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                <AppIcon icon={PlayIcon} size={14} color="#71717a" />
                <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                  {runCountText}
                </Text>
              </View>
            )}
          </View>

          {workflow.is_system_workflow && (
            <View
              style={{
                borderRadius: 6,
                paddingHorizontal: 8,
                paddingVertical: 2,
                backgroundColor: "rgba(0,187,255,0.12)",
              }}
            >
              <Text style={{ fontSize: fontSize.xs - 1, color: "#00bbff" }}>
                System
              </Text>
            </View>
          )}
        </View>
      </Pressable>

      {/* Actions context menu */}
      <Modal
        visible={menuVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setMenuVisible(false)}
      >
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.55)" }}
          onPress={() => setMenuVisible(false)}
        >
          <View
            style={{
              position: "absolute",
              top: "28%",
              alignSelf: "center",
              backgroundColor: "#1c1c1e",
              borderRadius: moderateScale(16, 0.5),
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.1)",
              minWidth: moderateScale(230, 0.5),
              overflow: "hidden",
            }}
          >
            {/* Menu header */}
            <View
              style={{
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm,
                borderBottomWidth: 1,
                borderBottomColor: "rgba(255,255,255,0.08)",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  fontWeight: "600",
                  color: "#ffffff",
                }}
                numberOfLines={1}
              >
                {workflow.title}
              </Text>
            </View>

            <ActionMenuItem
              icon={PlayIcon}
              label="Run Now"
              color="#00bbff"
              onPress={handleRun}
            />
            <ActionMenuDivider />
            <ActionMenuItem
              icon={PencilEdit02Icon}
              label="Edit"
              color="#ffffff"
              onPress={() => {
                setMenuVisible(false);
                router.push(`/(app)/workflows/${workflow.id}`);
              }}
            />
            <ActionMenuDivider />
            <ActionMenuItem
              icon={workflow.activated ? ToggleOffIcon : ToggleOnIcon}
              label={workflow.activated ? "Deactivate" : "Activate"}
              color={workflow.activated ? "#f59e0b" : "#22c55e"}
              onPress={handleToggleActivation}
            />
            <ActionMenuDivider />
            <ActionMenuItem
              icon={GlobeIcon}
              label={workflow.is_public ? "Unpublish" : "Publish"}
              color="#a78bfa"
              onPress={handlePublish}
            />
            <ActionMenuDivider />
            <ActionMenuItem
              icon={Delete02Icon}
              label="Delete"
              color="#ef4444"
              onPress={handleDelete}
            />
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

function ActionMenuItem({
  icon,
  label,
  color,
  onPress,
}: {
  icon: typeof PlayIcon;
  label: string;
  color: string;
  onPress: () => void;
}) {
  const { spacing, fontSize } = useResponsive();

  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.sm,
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm,
        backgroundColor: pressed ? "rgba(255,255,255,0.04)" : "transparent",
      })}
    >
      <AppIcon icon={icon} size={16} color={color} />
      <Text style={{ fontSize: fontSize.sm, color }}>{label}</Text>
    </Pressable>
  );
}

function ActionMenuDivider() {
  return (
    <View style={{ height: 1, backgroundColor: "rgba(255,255,255,0.06)" }} />
  );
}

function ExecutionStatusIndicator({ status }: { status: ExecutionStatusDot }) {
  if (status === "idle") return null;

  const dotColors: Record<Exclude<ExecutionStatusDot, "idle">, string> = {
    success: "#22c55e",
    failed: "#ef4444",
    running: "#f59e0b",
  };

  const dotColor = dotColors[status];

  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      <View
        style={{
          width: 8,
          height: 8,
          borderRadius: 4,
          backgroundColor: dotColor,
        }}
      />
      {status === "running" && (
        <Text style={{ fontSize: 10, color: dotColor }}>Running</Text>
      )}
    </View>
  );
}

function ActivationChip({ activated }: { activated: boolean }) {
  const { fontSize } = useResponsive();

  return (
    <View
      style={{
        borderRadius: 6,
        paddingHorizontal: 8,
        paddingVertical: 3,
        backgroundColor: activated
          ? "rgba(34,197,94,0.12)"
          : "rgba(239,68,68,0.12)",
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
      }}
    >
      <AppIcon
        icon={activated ? CheckmarkCircle02Icon : Cancel01Icon}
        size={12}
        color={activated ? "#22c55e" : "#ef4444"}
      />
      <Text
        style={{
          fontSize: fontSize.xs - 1,
          color: activated ? "#22c55e" : "#ef4444",
        }}
      >
        {activated ? "Activated" : "Deactivated"}
      </Text>
    </View>
  );
}

function WorkflowStepIcons({ steps }: { steps: Array<{ category: string }> }) {
  const categories = [...new Set(steps.map((s) => s.category))];
  const display = categories.slice(0, 3);

  if (display.length === 0) {
    return <View style={{ height: 32 }} />;
  }

  return (
    <View style={{ flexDirection: "row", alignItems: "center", height: 32 }}>
      {display.map((category, index) => {
        const iconElement = getToolCategoryIcon(category, {
          size: 16,
          showBackground: false,
        });
        return (
          <View
            key={category}
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              backgroundColor: "rgba(113,113,122,0.15)",
              alignItems: "center",
              justifyContent: "center",
              marginLeft: index > 0 ? -6 : 0,
              transform: [
                {
                  rotate:
                    display.length > 1
                      ? index % 2 === 0
                        ? "8deg"
                        : "-8deg"
                      : "0deg",
                },
              ],
              zIndex: index,
            }}
          >
            {iconElement ?? (
              <Text
                style={{
                  fontSize: 10,
                  color: "#a1a1aa",
                  fontWeight: "600",
                  textTransform: "uppercase",
                }}
                numberOfLines={1}
              >
                {category.slice(0, 2)}
              </Text>
            )}
          </View>
        );
      })}
      {categories.length > 3 && (
        <View
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            backgroundColor: "rgba(113,113,122,0.15)",
            alignItems: "center",
            justifyContent: "center",
            marginLeft: -6,
          }}
        >
          <Text style={{ fontSize: 10, color: "#a1a1aa" }}>
            +{categories.length - 3}
          </Text>
        </View>
      )}
    </View>
  );
}
