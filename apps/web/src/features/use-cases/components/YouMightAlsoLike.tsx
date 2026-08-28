"use client";

import { useEffect, useState } from "react";

import type { CommunityWorkflow } from "@/features/workflows/api/workflowApi";
import { workflowApi } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";

const EMPTY_CATEGORIES: string[] = [];

interface YouMightAlsoLikeProps {
  currentId: string;
  categories?: string[];
}

export default function YouMightAlsoLike({
  currentId,
  categories = EMPTY_CATEGORIES,
}: YouMightAlsoLikeProps) {
  const [items, setItems] = useState<CommunityWorkflow[]>([]);

  useEffect(() => {
    // Per-run cancellation flag (NOT a shared mountedRef): the cleanup runs
    // before every re-execution, so each run — including re-runs after
    // currentId/categories change on client-side navigation — may update
    // state. A one-shot ref would freeze recommendations permanently here.
    let cancelled = false;

    const fetchItems = async () => {
      try {
        const resp = await workflowApi.getExploreWorkflows(50, 0);
        let workflows = resp.workflows.filter((w) => w.id !== currentId);

        // If categories are provided, prioritize workflows in the same category
        if (categories.length > 0) {
          // Use Set for O(1) lookups instead of .includes() in loop
          const categorySet = new Set(categories);

          // Single loop instead of two .filter() passes
          const sameCategoryWorkflows: CommunityWorkflow[] = [];
          const otherWorkflows: CommunityWorkflow[] = [];
          for (const w of workflows) {
            if (w.categories?.some((cat) => categorySet.has(cat))) {
              sameCategoryWorkflows.push(w);
            } else {
              otherWorkflows.push(w);
            }
          }

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
          // No categories - use toSorted() for immutability
          workflows = workflows
            .toSorted((a, b) => {
              const aExecutions = a.total_executions || 0;
              const bExecutions = b.total_executions || 0;
              return bExecutions - aExecutions;
            })
            .slice(0, 6);
        }

        if (!cancelled) {
          setItems(workflows);
        }
      } catch (error) {
        console.error("Error fetching similar items:", error);
        if (!cancelled) {
          setItems([]);
        }
      }
    };

    fetchItems();

    return () => {
      cancelled = true;
    };
  }, [currentId, categories]);

  if (items.length === 0) return null;

  return (
    <div className="mx-auto max-w-5xl">
      <div className="my-20 border border-t border-zinc-900" />
      <div className="mx-auto space-y-6">
        <h2 className="mx-auto text-center font-serif text-6xl font-normal text-foreground">
          You might also like
        </h2>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((workflow) => (
            <UnifiedWorkflowCard
              key={workflow.id}
              communityWorkflow={workflow}
              variant="community"
              showCreator={true}
              href={workflow.slug ? `/use-cases/${workflow.slug}` : undefined}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
