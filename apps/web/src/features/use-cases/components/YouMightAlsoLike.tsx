"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { CommunityWorkflow } from "@/features/workflows/api/workflowApi";
import { workflowApi } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";

interface YouMightAlsoLikeProps {
  currentSlug: string;
  categories?: string[];
}

export default function YouMightAlsoLike({
  currentSlug,
  categories = [],
}: YouMightAlsoLikeProps) {
  const [items, setItems] = useState<CommunityWorkflow[]>([]);
  const router = useRouter();

  useEffect(() => {
    const fetchItems = async () => {
      try {
        const resp = await workflowApi.getExploreWorkflows(50, 0);
        let workflows = resp.workflows.filter((w) => w.id !== currentSlug);

        // If categories are provided, prioritize workflows in the same category
        if (categories.length > 0) {
          const sameCategoryWorkflows = workflows.filter((w) =>
            w.categories?.some((cat) => categories.includes(cat)),
          );
          const otherWorkflows = workflows.filter(
            (w) => !w.categories?.some((cat) => categories.includes(cat)),
          );

          // Sort by popularity (total_executions)
          const sortByPopularity = (
            a: CommunityWorkflow,
            b: CommunityWorkflow,
          ) => {
            const aExecutions = a.total_executions || 0;
            const bExecutions = b.total_executions || 0;
            return bExecutions - aExecutions;
          };

          sameCategoryWorkflows.sort(sortByPopularity);
          otherWorkflows.sort(sortByPopularity);

          // Take top 6: prioritize same category, then fill with others
          workflows = [
            ...sameCategoryWorkflows.slice(0, 6),
            ...otherWorkflows,
          ].slice(0, 6);
        } else {
          // No categories - just sort by popularity and take top 6
          workflows = workflows
            .sort((a, b) => {
              const aExecutions = a.total_executions || 0;
              const bExecutions = b.total_executions || 0;
              return bExecutions - aExecutions;
            })
            .slice(0, 6);
        }

        setItems(workflows);
      } catch (error) {
        console.error("Error fetching similar items:", error);
        setItems([]);
      }
    };

    fetchItems();
  }, [currentSlug, categories]);

  if (items.length === 0) return null;

  return (
    <div className="mx-auto max-w-7xl">
      <div className="my-20 border-[1px] border-t border-border-surface-400" />
      <div className="mx-auto space-y-6">
        <h2 className="mx-auto text-center font-serif text-6xl font-normal text-foreground">
          You might also like
        </h2>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {items.map((workflow) => (
            <UnifiedWorkflowCard
              key={workflow.id}
              communityWorkflow={workflow}
              variant="community"
              showCreator={true}
              onCardClick={() => {
                router.push(`/use-cases/${workflow.id}`);
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
