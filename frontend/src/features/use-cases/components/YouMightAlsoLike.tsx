"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { CommunityWorkflow } from "@/features/workflows/api/workflowApi";
import { workflowApi } from "@/features/workflows/api/workflowApi";
import CommunityWorkflowCard from "@/features/workflows/components/CommunityWorkflowCard";

interface YouMightAlsoLikeProps {
  currentSlug: string;
}

export default function YouMightAlsoLike({
  currentSlug,
}: YouMightAlsoLikeProps) {
  const [items, setItems] = useState<CommunityWorkflow[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  useEffect(() => {
    // Prevent fetching if already loading or if we already have items for this slug
    if (isLoading) return;

    const fetchItems = async () => {
      setIsLoading(true);
      try {
        const resp = await workflowApi.getExploreWorkflows(12, 0);
        const workflows = resp.workflows
          .filter((w) => w.id !== currentSlug)
          .sort(() => Math.random() - 0.5)
          .slice(0, 6);

        setItems(workflows);
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
          {items.map((workflow) => (
            <CommunityWorkflowCard
              key={workflow.id}
              workflow={workflow}
              onClick={() => {
                router.push(`/use-cases/${workflow.id}`);
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
