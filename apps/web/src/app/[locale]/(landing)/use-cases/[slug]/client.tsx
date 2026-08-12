"use client";

import { Avatar } from "@heroui/avatar";
import { PlayIcon, UserCircle02Icon } from "@icons";
import { useTransition } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import MetaInfoCard from "@/features/use-cases/components/MetaInfoCard";
import ToolsList from "@/features/use-cases/components/ToolsList";
import UseCaseDetailLayout from "@/features/use-cases/components/UseCaseDetailLayout";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import WorkflowSteps from "@/features/workflows/components/shared/WorkflowSteps";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";
import { getTriggerDisplayInfo } from "@/features/workflows/triggers/utils";
import { resolveCreatorAvatar } from "@/features/workflows/utils/creator";
import type { UseCase } from "@/types/features/workflowTypes";

interface UseCaseDetailClientProps {
  useCase: UseCase | null;
  communityWorkflow: Workflow | null;
  slug: string;
}

function buildWorkflowRequest(
  useCase: UseCase | null,
  communityWorkflow: Workflow | null,
) {
  const title = useCase?.title || communityWorkflow?.title;
  const description = useCase?.description || communityWorkflow?.description;
  const existingSteps = useCase?.steps || communityWorkflow?.steps;

  if (!title || !description) return null;

  // Convert PublicWorkflowStep to WorkflowStepData format if steps exist
  const formattedSteps = existingSteps?.map((step, index) => ({
    id: step.id || `step_${index}`,
    title: step.title,
    description: step.description,
    category: step.category,
  }));

  return {
    title,
    description,
    prompt: useCase?.prompt || communityWorkflow?.prompt || description,
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
}

function deriveCreatorInfo(communityWorkflow: Workflow | null) {
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
        : undefined;
  const creatorRecord = hasCreatorObject
    ? communityWorkflow.creator
    : communityWorkflow?.created_by
      ? { id: communityWorkflow.created_by }
      : null;

  return {
    creatorName,
    creatorAvatar: resolveCreatorAvatar(creatorRecord),
    showCreator: !!communityWorkflow && !!creatorName,
  };
}

function deriveRunCountText(communityWorkflow: Workflow | null) {
  const runCount = communityWorkflow
    ? communityWorkflow.metadata?.total_executions ||
      communityWorkflow.total_executions ||
      0
    : 0;
  return runCount === 0
    ? "Never"
    : `${runCount} ${runCount === 1 ? "time" : "times"}`;
}

function deriveFormattedSteps(
  useCase: UseCase | null,
  communityWorkflow: Workflow | null,
) {
  if (!useCase) return communityWorkflow?.steps;
  return useCase.steps?.map((step, index) => ({
    id: `step-${index}`,
    title: step.title,
    description: step.description,
    category: useCase.integrations[index % useCase.integrations.length],
  }));
}

export default function UseCaseDetailClient({
  useCase,
  communityWorkflow,
  slug,
}: UseCaseDetailClientProps) {
  const [isCreating, startCreateTransition] = useTransition();
  const { createWorkflow } = useWorkflowCreation();
  const { selectWorkflow } = useWorkflowSelection();
  const { integrations } = useIntegrations();

  // Auth check
  const { isAuthenticated, openLoginModal } = useAuth();

  const handleCreateWorkflow = () => {
    // Check authentication first - open login modal if not authenticated
    if (!isAuthenticated) {
      openLoginModal();
      return;
    }

    const workflowRequest = buildWorkflowRequest(useCase, communityWorkflow);
    if (!workflowRequest) return;

    startCreateTransition(async () => {
      try {
        const result = await createWorkflow(workflowRequest);

        if (result.success && result.workflow)
          selectWorkflow(result.workflow, { autoSend: false });
      } catch (error) {
        console.error("Workflow creation error:", error);
      }
    });
  };

  const data = useCase || communityWorkflow;
  if (!data) return null;

  // Prepare common data
  const title = "title" in data ? data.title : "";
  const currentSlug = useCase?.slug ?? communityWorkflow?.slug ?? slug;

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

  const { creatorName, creatorAvatar, showCreator } =
    deriveCreatorInfo(communityWorkflow);

  // Prepare tools - Type-safe extraction from steps, mapped to Tool format for ToolsList.
  // Dedupe by category so a workflow with multiple steps using the same tool only
  // renders one chip in the tools list.
  const tools = Array.from(
    new Map(
      (useCase?.steps || communityWorkflow?.steps || []).map((step) => [
        step.category,
        { name: step.category, category: step.category },
      ]),
    ).values(),
  );

  const runCountText = deriveRunCountText(communityWorkflow);

  // Prepare trigger info (only for community workflows)
  const triggerInfo = communityWorkflow
    ? getTriggerDisplayInfo(communityWorkflow, integrations)
    : null;
  const shouldShowTrigger =
    communityWorkflow && communityWorkflow.trigger_config.type !== "manual";

  // Prepare steps
  const steps = useCase?.steps || communityWorkflow?.steps;
  const stepsFormatted = deriveFormattedSteps(useCase, communityWorkflow);

  return (
    <div className="relative">
      <UseCaseDetailLayout
        breadcrumbs={breadcrumbs}
        title={title}
        id={currentSlug}
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
