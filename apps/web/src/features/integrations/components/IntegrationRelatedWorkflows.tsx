"use client";

import { CircleArrowUpRightIcon } from "@icons";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";
import { integrationsApi } from "../api/integrationsApi";

interface IntegrationRelatedWorkflowsProps {
  /** The integration slug or native integration ID */
  readonly integrationId: string;
  /** Max number of workflows to fetch */
  readonly limit?: number;
  /**
   * Visual variant.
   * - "sidebar" (default): compact heading, no card wrapper. For use in side panels.
   * - "section": full marketplace section styling (rounded-3xl card, large heading).
   */
  readonly variant?: "sidebar" | "section";
  /** Optional name of the integration to personalise the section copy. */
  readonly integrationName?: string;
}

const VIEW_MORE_HREF = "/use-cases#community-section";

function ViewMoreCard() {
  return (
    <Link
      href={VIEW_MORE_HREF}
      aria-label="View more workflows"
      className="group flex w-60 shrink-0 flex-col items-center justify-center gap-2 rounded-3xl border border-dashed border-zinc-700/60 bg-transparent text-zinc-400 transition-colors hover:border-transparent hover:bg-zinc-800 hover:text-zinc-100"
    >
      <CircleArrowUpRightIcon
        width={28}
        height={28}
        className="transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
      />
      <span className="text-sm font-medium">View more</span>
    </Link>
  );
}

export function IntegrationRelatedWorkflows({
  integrationId,
  limit = 4,
  variant = "sidebar",
  integrationName,
}: Readonly<IntegrationRelatedWorkflowsProps>) {
  const { data, isLoading } = useQuery({
    queryKey: ["integration-workflows", integrationId, limit],
    queryFn: () => integrationsApi.getRelatedWorkflows(integrationId, limit),
    staleTime: 5 * 60 * 1000,
  });

  // Render nothing until data is resolved AND we have something to show.
  // This avoids the "skeleton flash → empty collapse" jank for integrations
  // that have zero matching workflows.
  if (isLoading) return null;

  const workflows = (data?.workflows ?? []) as CommunityWorkflow[];
  if (workflows.length === 0) return null;

  const list = (
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
      <ViewMoreCard />
    </section>
  );

  if (variant === "section") {
    return (
      <section className="rounded-3xl bg-zinc-900/50 backdrop-blur-md p-8 space-y-6">
        <div>
          <h2 className="text-2xl font-medium text-foreground mb-2">
            Workflows that use this integration
          </h2>
          <p className="text-zinc-400 text-sm leading-relaxed">
            {integrationName
              ? `Community-built workflows that automate ${integrationName} with GAIA. Clone any of them in one click.`
              : "Community-built workflows powered by this integration. Clone any of them in one click."}
          </p>
        </div>
        {list}
      </section>
    );
  }

  return (
    <div className="flex flex-col gap-2 mt-6">
      <h2 className="text-sm font-medium text-zinc-300">
        Workflows that use this integration
      </h2>
      {list}
    </div>
  );
}
