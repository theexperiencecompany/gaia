"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { UseCase } from "@/features/use-cases/types";
import type {
  CommunityWorkflow,
  Workflow,
} from "@/features/workflows/api/workflowApi";
import { workflowApi } from "@/features/workflows/api/workflowApi";
import CommunityWorkflowCard from "@/features/workflows/components/CommunityWorkflowCard";

import UseCaseCard from "./UseCaseCard";

interface YouMightAlsoLikeProps {
  currentSlug: string;
}

export default function YouMightAlsoLike({
  currentSlug,
}: YouMightAlsoLikeProps) {
  const [items, setItems] = useState<(UseCase | Workflow)[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  useEffect(() => {
    // Prevent fetching if already loading or if we already have items for this slug
    if (isLoading) return;

    const fetchItems = async () => {
      setIsLoading(true);
      try {
        // TODO: Implement proper recommendation algorithm based on:
        // - Categories/tags
        // - Tool usage similarity
        // - User behavior/preferences
        // - Popularity metrics

        // Fetch explore workflows from API and convert to UseCase-like objects
        const resp = await workflowApi.getExploreWorkflows(12, 0);
        const useCases = resp.workflows
          .filter((w) => w.id !== currentSlug)
          .map((w) => ({
            title: w.title,
            description: w.description,
            action_type: "workflow" as const,
            integrations:
              w.steps
                ?.map((s) => s.tool_category)
                .filter((v, i, a) => a.indexOf(v) === i) || [],
            categories: w.categories || ["featured"],
            published_id: w.id,
            slug: w.id,
            steps: w.steps,
            creator: w.creator,
          }))
          .sort(() => Math.random() - 0.5)
          .slice(0, 6);

        setItems(useCases as (UseCase | Workflow)[]);
      } catch (error) {
        console.error("Error fetching similar items:", error);
        setItems([]);
      } finally {
        setIsLoading(false);
      }
    };

    fetchItems();
  }, [currentSlug]);

  if (items.length === 0) return null;

  return (
    <div className="mx-auto max-w-7xl">
      <div className="my-20 border-[1px] border-t border-zinc-900" />
      <div className="mx-auto space-y-6">
        <h2 className="mx-auto text-center font-serif text-6xl font-normal text-foreground">
          You might also like
        </h2>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {items.map((item) => {
            const isUseCase = "slug" in item;

            return isUseCase ? (
              <UseCaseCard
                key={item.slug}
                title={(item as UseCase).title}
                description={(item as UseCase).description}
                action_type={(item as UseCase).action_type}
                prompt={(item as UseCase).prompt}
                slug={(item as UseCase).slug}
              />
            ) : (
              <CommunityWorkflowCard
                key={item.id}
                workflow={item as CommunityWorkflow}
                onClick={() => {
                  router.push(`/use-cases/${item.id}`);
                }}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
