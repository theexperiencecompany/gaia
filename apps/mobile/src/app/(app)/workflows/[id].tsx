import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { WorkflowDetailScreen } from "@/features/workflows/components/workflow-detail-screen";
import { useWorkflowDetail } from "@/features/workflows/hooks/use-workflow-detail";
import type { Workflow } from "@/features/workflows/types/workflow-types";

function normalizeId(raw: string | string[] | undefined): string | null {
  if (!raw) return null;
  const value = Array.isArray(raw) ? raw[0] : raw;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

export default function WorkflowDetailPage() {
  const { id } = useLocalSearchParams<{ id?: string | string[] }>();
  const workflowId = useMemo(() => normalizeId(id), [id]);
  const router = useRouter();

  const {
    workflow: fetchedWorkflow,
    executions,
    executionsTotal,
    hasMoreExecutions,
    isLoading,
    isLoadingExecutions,
    error,
    loadMoreExecutions,
  } = useWorkflowDetail(workflowId);

  const [localWorkflow, setLocalWorkflow] = useState<Workflow | null>(null);
  const workflow = localWorkflow ?? fetchedWorkflow;

  const handleUpdated = useCallback((updated: Workflow) => {
    setLocalWorkflow(updated);
  }, []);

  const handleActivationToggled = useCallback((updated: Workflow) => {
    setLocalWorkflow(updated);
  }, []);

  const handleDeleted = useCallback(() => {
    router.back();
  }, [router]);

  const handleBack = useCallback(() => {
    router.back();
  }, [router]);

  return (
    <WorkflowDetailScreen
      workflowId={workflowId ?? ""}
      workflow={workflow}
      executions={executions}
      executionsTotal={executionsTotal}
      hasMoreExecutions={hasMoreExecutions}
      isLoading={isLoading}
      isLoadingExecutions={isLoadingExecutions}
      error={error}
      onBack={handleBack}
      onDeleted={handleDeleted}
      onUpdated={handleUpdated}
      onActivationToggled={handleActivationToggled}
      onLoadMoreExecutions={() => void loadMoreExecutions()}
    />
  );
}
