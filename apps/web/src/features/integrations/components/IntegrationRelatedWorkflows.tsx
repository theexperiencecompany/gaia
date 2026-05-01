"use client";

import { Skeleton } from "@heroui/skeleton";
import { useQuery } from "@tanstack/react-query";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";
import { integrationsApi } from "../api/integrationsApi";

interface IntegrationRelatedWorkflowsProps {
  /** The integration slug or native integration ID */
  integrationId: string;
  /** Max number of workflows to fetch */
  limit?: number;
}

export function IntegrationRelatedWorkflows({
  integrationId,
  limit = 10,
}: IntegrationRelatedWorkflowsProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["integration-workflows", integrationId, limit],
    queryFn: () => integrationsApi.getRelatedWorkflows(integrationId, limit),
    staleTime: 5 * 60 * 1000,
  });

  const workflows = (data?.workflows ?? []) as CommunityWorkflow[];

  if (!isLoading && workflows.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-sm font-medium text-zinc-300">
        Workflows that use this Integration
      </h2>

      {isLoading ? (
        <div className="flex gap-3 overflow-hidden">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton
              key={i}
              className="h-36 w-60 shrink-0 rounded-3xl bg-zinc-800"
            />
          ))}
        </div>
      ) : (
        <div
          role="region"
          aria-label="Related workflows"
          tabIndex={0}
          className="flex gap-3 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          style={{ WebkitOverflowScrolling: "touch" }}
        >
          {workflows.map((workflow) => (
            <div key={workflow.id} className="w-60 shrink-0">
              <UnifiedWorkflowCard
                communityWorkflow={workflow}
                variant="community"
                showCreator={false}
                showExecutions={false}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
