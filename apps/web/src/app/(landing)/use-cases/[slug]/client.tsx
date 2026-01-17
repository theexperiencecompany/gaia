"use client";

import { Avatar } from "@heroui/avatar";
import { PlayIcon } from "@theexperiencecompany/gaia-icons/solid-standard";
import Image from "next/image";
import { useState } from "react";

import { wallpapers } from "@/config/wallpapers";
import { useLoginModalActions } from "@/features/auth/hooks/useLoginModal";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import MetaInfoCard from "@/features/use-cases/components/MetaInfoCard";
import ToolsList from "@/features/use-cases/components/ToolsList";
import UseCaseDetailLayout from "@/features/use-cases/components/UseCaseDetailLayout";
import type { UseCase } from "@/features/use-cases/types";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import WorkflowSteps from "@/features/workflows/components/shared/WorkflowSteps";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";
import { getTriggerDisplay } from "@/features/workflows/utils/triggerDisplay";
import { UserCircle02Icon } from "@/icons";
import { useUserStore } from "@/stores/userStore";

interface UseCaseDetailClientProps {
  useCase: UseCase | null;
  communityWorkflow: Workflow | null;
  slug: string;
}

export default function UseCaseDetailClient({
  useCase,
  communityWorkflow,
  slug,
}: UseCaseDetailClientProps) {
  const [isCreating, setIsCreating] = useState(false);
  const { createWorkflow } = useWorkflowCreation();
  const { selectWorkflow } = useWorkflowSelection();
  const { integrations } = useIntegrations();

  // Auth check
  const userEmail = useUserStore((state) => state.email);
  const isAuthenticated = Boolean(userEmail);
  const { openModal: openLoginModal } = useLoginModalActions();

  const handleCreateWorkflow = async () => {
    // Check authentication first - open login modal if not authenticated
    if (!isAuthenticated) {
      openLoginModal();
      return;
    }

    const title = useCase?.title || communityWorkflow?.title;
    const description = useCase?.description || communityWorkflow?.description;
    const existingSteps = useCase?.steps || communityWorkflow?.steps;

    if (!title || !description) return;

    setIsCreating(true);
    try {
      // Convert PublicWorkflowStep to WorkflowStepData format if steps exist
      const formattedSteps = existingSteps?.map((step, index) => ({
        id: step.id || `step_${index}`,
        title: step.title,
        description: step.description,
        category: step.category,
      }));

      const workflowRequest = {
        title,
        description,
        trigger_config: {
          type: "manual" as const,
          enabled: true,
        },
        // Pass formatted steps if available to avoid regeneration
        ...(formattedSteps &&
          formattedSteps.length > 0 && {
            steps: formattedSteps,
          }),
        // Only generate if no steps exist
        generate_immediately: !formattedSteps || formattedSteps.length === 0,
      };

      const result = await createWorkflow(workflowRequest);

      if (result.success && result.workflow)
        selectWorkflow(result.workflow, { autoSend: false });
    } catch (error) {
      console.error("Workflow creation error:", error);
    } finally {
      setIsCreating(false);
    }
  };

  const data = useCase || communityWorkflow;
  if (!data) return null;

  // Prepare common data
  const title = "title" in data ? data.title : "";
  const currentSlug = useCase?.slug || communityWorkflow?.id || slug;

  // Prepare breadcrumbs
  const breadcrumbs = [
    { label: "Home", href: "/" },
    { label: "Use Cases", href: "/use-cases" },
    {
      label: useCase
        ? useCase.categories.find((cat) => cat !== "featured") ||
          useCase.categories[0]
        : "Community",
    },
  ];

  // Prepare creator info (only for community workflows)
  const hasCreatorObject =
    communityWorkflow &&
    "creator" in communityWorkflow &&
    communityWorkflow.creator;
  const creatorName = hasCreatorObject
    ? communityWorkflow.creator?.name
    : communityWorkflow?.created_by
      ? "Community Member"
      : communityWorkflow
        ? "GAIA Team"
        : null;
  const creatorAvatar = hasCreatorObject
    ? communityWorkflow.creator?.avatar
    : undefined;
  const showCreator = !!communityWorkflow && !!creatorName;

  // Prepare tools - Type-safe extraction from steps, mapped to Tool format for ToolsList
  const tools = (useCase?.steps || communityWorkflow?.steps || []).map(
    (step) => ({
      name: step.category,
      category: step.category,
    }),
  );

  // Prepare run count
  const runCount = communityWorkflow
    ? communityWorkflow.metadata?.total_executions ||
      communityWorkflow.total_executions ||
      0
    : 0;
  const runCountText =
    runCount === 0
      ? "Never"
      : `${runCount} ${runCount === 1 ? "time" : "times"}`;

  // Prepare trigger info (only for community workflows)
  const triggerInfo = communityWorkflow
    ? getTriggerDisplay(communityWorkflow, integrations)
    : null;
  const shouldShowTrigger =
    communityWorkflow && communityWorkflow.trigger_config.type !== "manual";

  // Prepare steps
  const steps = useCase?.steps || communityWorkflow?.steps;
  const stepsFormatted = useCase
    ? useCase.steps?.map((step, index) => ({
        id: `step-${index}`,
        title: step.title,
        description: step.description,
        category: useCase.integrations[index % useCase.integrations.length],
      }))
    : communityWorkflow?.steps;

  return (
    <div className="relative">
      <Image
        src={wallpapers.useCases.webp}
        alt="GAIA Use-Cases Wallpaper"
        priority
        fill
        className="mask-[linear-gradient(to_bottom,transparent_0%,black_20%,black_80%,transparent_100%)] object-cover opacity-15 z-0 w-screen fixed h-screen left-0 top-0 max-h-screen"
      />
      <UseCaseDetailLayout
        breadcrumbs={breadcrumbs}
        title={title}
        slug={currentSlug}
        isCreating={isCreating}
        onCreateWorkflow={handleCreateWorkflow}
        metaInfo={
          <>
            {showCreator && (
              <MetaInfoCard
                icon={
                  <Avatar
                    src={creatorAvatar}
                    name={creatorName}
                    size="sm"
                    fallback={
                      <UserCircle02Icon className="h-8 w-8 text-zinc-300" />
                    }
                  />
                }
                label="Created by"
                value={creatorName}
              />
            )}

            {/* Tools */}
            {tools && tools.length > 0 && <ToolsList tools={tools} />}

            {/* Run Count */}
            <MetaInfoCard
              icon={<PlayIcon className="h-7 w-7 text-zinc-400" />}
              label="Ran"
              value={runCountText}
            />

            {/* Trigger */}
            {shouldShowTrigger && triggerInfo && (
              <MetaInfoCard
                icon={
                  triggerInfo.integrationId
                    ? getToolCategoryIcon(triggerInfo.integrationId, {
                        size: 20,
                        width: 20,
                        height: 20,
                        showBackground: false,
                      })
                    : undefined
                }
                label="Trigger"
                value={<span className="capitalize">{triggerInfo.label}</span>}
              />
            )}
          </>
        }
        // detailedContent={}
        description={
          useCase?.detailed_description ||
          useCase?.description ||
          communityWorkflow?.description
        }
        steps={
          steps && steps.length > 0 ? (
            <div className="w-fit shrink-0">
              <div className="sticky top-8 rounded-3xl bg-zinc-900 px-6 pt-4 pb-2">
                <div className="text-sm font-medium text-zinc-500 mb-3">
                  Workflow Steps:
                </div>
                <WorkflowSteps steps={stepsFormatted || []} size="large" />
              </div>
            </div>
          ) : undefined
        }
        categories={
          useCase?.categories ||
          (communityWorkflow?.metadata?.category
            ? [communityWorkflow.metadata.category]
            : [])
        }
      />
      <FinalSection />
    </div>
  );
}
