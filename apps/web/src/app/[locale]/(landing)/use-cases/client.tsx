"use client";

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

  return (
    <>
      <div className="relative z-1 container mx-auto pb-8 px-4 sm:px-6">
        <div className="mb-8 text-center">
          <h1 className="mb-1 font-serif text-4xl sm:text-6xl md:text-8xl font-normal">
            See what's Possible
          </h1>
          <p className="mx-auto max-w-3xl text-lg text-zinc-300/80">
            These are the workflows GAIA runs for people every day: triaging
            email, preparing for meetings, protecting focus time, turning
            conversations into tasks, and keeping the tools a project depends on
            in sync. Filter by category to find a pattern close to your own
            work, then open a use case to see the trigger, the steps involved,
            and the tools it uses. You can run a workflow as shown, adapt it to
            your accounts, or describe the outcome you want in plain English and
            let GAIA assemble the equivalent. The community section below
            collects workflows published by other users; open one to see how it
            is built, then run it yourself. New examples appear as the product
            and the community grow.
          </p>
        </div>
        <UseCaseSection
          dummySectionRef={contentRef}
          options={{ useBlurEffect: true }}
        />
        <div id="community-section" className="mt-22 space-y-6">
          <div className="mb-14 text-center">
            <h2 className="mb-1 font-serif text-3xl sm:text-5xl md:text-6xl font-normal">
              Published by The Community
            </h2>
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
                  useBlurEffect={true}
                  variant="community"
                  showCreator={true}
                  href={
                    workflow.slug ? `/use-cases/${workflow.slug}` : undefined
                  }
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
