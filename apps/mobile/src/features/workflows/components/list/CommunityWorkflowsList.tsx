import { ActivityIndicator, Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { WORKFLOW_COLORS } from "../../constants/colors";
import type { CommunityWorkflow } from "../../types/workflow-types";
import { CommunityWorkflowCard } from "../community-workflow-card";
import { SectionHeader } from "../section-header";
import { WorkflowListSkeleton } from "../workflow-skeletons";

interface CommunityWorkflowsListProps {
  workflows: CommunityWorkflow[];
  isLoading: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
}

export function CommunityWorkflowsList({
  workflows,
  isLoading,
  isLoadingMore,
  hasMore,
  onLoadMore,
}: CommunityWorkflowsListProps) {
  const { spacing, fontSize } = useResponsive();

  if (isLoading) {
    return (
      <View style={{ gap: spacing.md }}>
        <SectionHeader
          title="Community Workflows"
          description="Check out what others have built and grab anything that looks useful!"
        />
        <WorkflowListSkeleton />
      </View>
    );
  }

  if (workflows.length === 0) return null;

  return (
    <View style={{ gap: spacing.md }}>
      <SectionHeader
        title="Community Workflows"
        description="Check out what others have built and grab anything that looks useful!"
        count={workflows.length}
      />
      <View style={{ gap: spacing.sm }}>
        {workflows.map((w) => (
          <CommunityWorkflowCard key={w.id} workflow={w} />
        ))}
      </View>

      {hasMore ? (
        <Pressable
          onPress={onLoadMore}
          disabled={isLoadingMore}
          style={{
            alignItems: "center",
            paddingVertical: spacing.sm,
            gap: 6,
          }}
        >
          {isLoadingMore ? (
            <ActivityIndicator size="small" color={WORKFLOW_COLORS.primary} />
          ) : (
            <Text
              style={{
                fontSize: fontSize.sm,
                color: WORKFLOW_COLORS.primary,
                fontWeight: "600",
              }}
            >
              Load more
            </Text>
          )}
        </Pressable>
      ) : null}
    </View>
  );
}
