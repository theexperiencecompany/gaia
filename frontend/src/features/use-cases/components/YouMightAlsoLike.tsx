"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  type UseCase,
  useCasesData,
} from "@/features/use-cases/constants/dummy-data";
import {
  CommunityWorkflow,
  Workflow,
} from "@/features/workflows/api/workflowApi";
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

        // Get static use cases, filter current, and randomly shuffle
        const filtered = useCasesData
          .filter((uc) => uc.slug !== currentSlug)
          .sort(() => Math.random() - 0.5)
          .slice(0, 6);
        setItems(filtered);
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
    <>
      <div className="my-20 border-[1px] border-t border-zinc-900" />
      <div className="space-y-6">
        <h2 className="mx-auto text-center font-serif text-6xl font-normal text-foreground">
          You might also like
        </h2>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item) => {
            const isUseCase = "slug" in item;

            return isUseCase ? (
              <UseCaseCard
                key={item.slug}
                title={(item as UseCase).title}
                description={(item as UseCase).description}
                action_type={(item as UseCase).action_type}
                integrations={(item as UseCase).integrations}
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
    </>
  );
}
