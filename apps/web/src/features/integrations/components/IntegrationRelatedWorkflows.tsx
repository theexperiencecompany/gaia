"use client";

import { Skeleton } from "@heroui/skeleton";
import { useQuery } from "@tanstack/react-query";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";
import { integrationsApi } from "../api/integrationsApi";

interface IntegrationRelatedWorkflowsProps {
  /** The integration slug or native integration ID */
  readonly integrationId: string;
  /** Max number of workflows to fetch */
  readonly limit?: number;
}

export function IntegrationRelatedWorkflows({
  integrationId,
  limit = 10,
}: Readonly<IntegrationRelatedWorkflowsProps>) {
  const { data, isLoading } = useQuery({
    queryKey: ["integration-workflows", integrationId, limit],
    queryFn: () => integrationsApi.getRelatedWorkflows(integrationId, limit),
    staleTime: 5 * 60 * 1000,
  });

  const workflows = (data?.workflows ?? []) as CommunityWorkflow[];

  if (!isLoading && workflows.length === 0) {
    return (
      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-zinc-100">
          Workflows that use this Integration
        </h2>
        <p className="text-sm text-zinc-500">
          No workflows found for this integration.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-sm font-medium text-zinc-100">
        Workflows that use this Integration
      </h2>

      {isLoading ? (
        <div className="flex gap-3 overflow-hidden">
          {["s1", "s2", "s3"].map((key) => (
            <Skeleton
              key={key}
              className="h-36 w-60 shrink-0 rounded-3xl bg-zinc-800"
            />
          ))}
        </div>
      ) : (
        <section
          aria-label="Workflows that use this integration"
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
        </section>
      )}
    </div>
  );
}
