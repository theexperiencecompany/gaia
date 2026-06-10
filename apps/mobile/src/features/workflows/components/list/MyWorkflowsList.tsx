import { Pressable, View } from "react-native";
import { AppIcon, FlowCircleIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { AppEmptyStateCard } from "@/shared/components/ui/app-empty-state-card";
import { WORKFLOW_COLORS } from "../../constants/colors";
import type { Workflow } from "../../types/workflow-types";
import { SectionHeader } from "../section-header";
import { WorkflowCard } from "../workflow-card";
import { WorkflowListSkeleton } from "../workflow-skeletons";

interface MyWorkflowsListProps {
  workflows: Workflow[];
  isLoading: boolean;
  error: string | null;
  onRefetch: () => void;
  onCreate: () => void;
  onUpdated: () => void;
}

export function MyWorkflowsList({
  workflows,
  isLoading,
  error,
  onRefetch,
  onCreate,
  onUpdated,
}: MyWorkflowsListProps) {
  const { spacing, fontSize } = useResponsive();

  const renderBody = () => {
    if (isLoading) return <WorkflowListSkeleton />;

    if (error) {
      return (
        <View
          style={{
            paddingVertical: spacing.xl,
            alignItems: "center",
            gap: spacing.md,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.sm,
              color: WORKFLOW_COLORS.dangerText,
              textAlign: "center",
            }}
          >
            {error}
          </Text>
          <Pressable onPress={onRefetch}>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: WORKFLOW_COLORS.primary,
                fontWeight: "600",
              }}
            >
              Try again
            </Text>
          </Pressable>
        </View>
      );
    }

    if (workflows.length === 0) {
      return (
        <AppEmptyStateCard
          title="No workflows yet"
          description="Create your first workflow to get started."
          icon={
            <AppIcon
              icon={FlowCircleIcon}
              size={36}
              color={WORKFLOW_COLORS.textZinc700}
            />
          }
          action={{
            label: "Create your first workflow",
            onPress: onCreate,
            variant: "primary",
            size: "sm",
          }}
          className="rounded-2xl bg-zinc-800/30"
        />
      );
    }

    return (
      <View style={{ gap: spacing.sm }}>
        {workflows.map((workflow) => (
          <WorkflowCard
            key={workflow.id}
            workflow={workflow}
            onUpdated={onUpdated}
          />
        ))}
      </View>
    );
  };

  return (
    <View style={{ gap: spacing.md }}>
      <SectionHeader
        title="My Workflows"
        description="Automate tasks and run workflows on demand or on a schedule."
        count={
          !isLoading && workflows.length > 0 ? workflows.length : undefined
        }
      />
      {renderBody()}
    </View>
  );
}
