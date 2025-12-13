"use client";

import { useRouter } from "next/navigation";
import { useRef } from "react";

import FinalSection from "@/features/landing/components/sections/FinalSection";
import PublishWorkflowCTA from "@/features/use-cases/components/PublishWorkflowCTA";
import UseCaseSection from "@/features/use-cases/components/UseCaseSection";
import type { CommunityWorkflow } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";

interface UseCasesPageClientProps {
  communityWorkflows: CommunityWorkflow[];
}

export default function UseCasesPageClient({
  communityWorkflows,
}: UseCasesPageClientProps) {
  const contentRef = useRef(null);
  const router = useRouter();

  return (
    <>
      <div className="relative z-[1] container mx-auto pb-8">
        <div className="mb-8 text-center">
          <h1 className="mb-1 font-serif text-8xl font-normal">
            See what's Possible
          </h1>
          <p className="mx-auto max-w-3xl text-lg text-zinc-300/80">
            Practical use cases showing how GAIA works for you
          </p>
        </div>

        <UseCaseSection dummySectionRef={contentRef} />

        <div id="community-section" className="mt-22 space-y-6">
          <div className="mb-14 text-center">
            <h1 className="mb-1 font-serif text-6xl font-normal">
              Published by The Community
            </h1>
            <p className="mx-auto max-w-3xl text-lg text-zinc-300/80">
              Discover what others are building with GAIA
            </p>
          </div>
          {communityWorkflows.length === 0 ? (
            <div className="flex h-48 items-center justify-center">
              <div className="text-foreground-500">
                No community workflows available yet
              </div>
            </div>
          ) : (
            <div className="mx-auto grid max-w-7xl grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-4">
              {communityWorkflows.map((workflow) => (
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
          )}
        </div>
      </div>

      <PublishWorkflowCTA />
      <FinalSection />
    </>
  );
}
