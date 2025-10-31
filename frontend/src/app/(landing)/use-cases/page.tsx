import Image from "next/image";

import UseCasesPageClient from "@/app/(landing)/use-cases/client";
import {
  CommunityWorkflow,
  workflowApi,
} from "@/features/workflows/api/workflowApi";

export const revalidate = 3600; // Revalidate every hour

export default async function UseCasesPage() {
  let communityWorkflows: CommunityWorkflow[] = [];

  try {
    const response = await workflowApi.getCommunityWorkflows(8, 0);
    communityWorkflows = response.workflows;
  } catch (error) {
    console.error("Error loading community workflows:", error);
  }

  return (
    <div className="relative h-fit min-h-screen pt-110">
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

      <UseCasesPageClient communityWorkflows={communityWorkflows} />
    </div>
  );
}
