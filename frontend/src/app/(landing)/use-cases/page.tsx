"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import Spinner from "@/components/ui/shadcn/spinner";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import UseCaseSection from "@/features/use-cases/components/UseCaseSection";
import {
  CommunityWorkflow,
  workflowApi,
} from "@/features/workflows/api/workflowApi";
import CommunityWorkflowCard from "@/features/workflows/components/CommunityWorkflowCard";

export default function UseCasesPage() {
  const [communityWorkflows, setCommunityWorkflows] = useState<
    CommunityWorkflow[]
  >([]);
  const contentRef = useRef(null);

  const [isLoadingCommunity, setIsLoadingCommunity] = useState(false);

  // Load community workflows
  useEffect(() => {
    const loadCommunityWorkflows = async () => {
      setIsLoadingCommunity(true);
      try {
        const response = await workflowApi.getCommunityWorkflows(8, 0);
        setCommunityWorkflows(response.workflows);
      } catch (error) {
        console.error("Error loading community workflows:", error);
      } finally {
        setIsLoadingCommunity(false);
      }
    };

    loadCommunityWorkflows();
  }, []);

  return (
    <div className="relative h-fit min-h-screen pt-110" ref={contentRef}>
      <div className="absolute inset-0 top-0 z-0 h-[70vh] w-[100%]">
        <Image
          src={"/images/wallpapers/meadow.webp"}
          alt="GAIA Use-Cases Wallpaper"
          sizes="100vw"
          priority
          fill
          className="aspect-video object-cover object-center opacity-80"
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[40vh] bg-gradient-to-t from-background to-transparent" />
      </div>

      <div
        className="relative z-[1] container mx-auto px-6 pb-8"
        // disableIntersectionObserver={true}
      >
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
          {isLoadingCommunity ? (
            <div className="flex h-48 items-center justify-center">
              <Spinner />
            </div>
          ) : communityWorkflows.length === 0 ? (
            <div className="flex h-48 items-center justify-center">
              <div className="text-lg text-foreground-500">
                No community workflows available yet
              </div>
            </div>
          ) : (
            <div className="mx-auto grid max-w-7xl grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3">
              {communityWorkflows.map((workflow) => (
                <CommunityWorkflowCard key={workflow.id} workflow={workflow} />
              ))}
            </div>
          )}
        </div>
      </div>

      <FinalSection />
    </div>
  );
}
