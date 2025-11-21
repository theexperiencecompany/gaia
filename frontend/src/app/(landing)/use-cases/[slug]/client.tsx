"use client";

import { Avatar } from "@heroui/avatar";
import { useState } from "react";

import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import MetaInfoCard from "@/features/use-cases/components/MetaInfoCard";
import ToolsList from "@/features/use-cases/components/ToolsList";
import UseCaseDetailLayout from "@/features/use-cases/components/UseCaseDetailLayout";
import { UseCase } from "@/features/use-cases/types";
import { Workflow } from "@/features/workflows/api/workflowApi";
import WorkflowSteps from "@/features/workflows/components/shared/WorkflowSteps";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";
import { getTriggerDisplay } from "@/features/workflows/utils/triggerDisplay";
import { Play, User } from "@/icons";

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

  const handleCreateWorkflow = async () => {
    const title = useCase?.title || communityWorkflow?.title;
    const description = useCase?.description || communityWorkflow?.description;

    if (!title || !description) return;

    setIsCreating(true);
    try {
      const workflowRequest = {
        title,
        description,
        trigger_config: {
          type: "manual" as const,
          enabled: true,
        },
        generate_immediately: true,
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
  const description = "description" in data ? data.description : "";
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
  const tools = (useCase?.steps || communityWorkflow?.steps || [])
    .filter((step) => step.tool_name)
    .map((step) => ({
      name: step.tool_name || step.tool_category,
      category: step.tool_category,
    }));

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
        tool_name: useCase.integrations[index % useCase.integrations.length],
        tool_category:
          useCase.integrations[index % useCase.integrations.length],
      }))
    : communityWorkflow?.steps;

  return (
    <>
      <UseCaseDetailLayout
        breadcrumbs={breadcrumbs}
        title={title}
        description={useCase ? description : undefined}
        slug={currentSlug}
        isCreating={isCreating}
        onCreateWorkflow={handleCreateWorkflow}
        metaInfo={
          <>
            {/* Creator - only for community workflows */}
            {showCreator && (
              <MetaInfoCard
                icon={
                  <Avatar
                    src={creatorAvatar}
                    name={creatorName}
                    size="sm"
                    fallback={
                      <User className="h-4 w-4 text-primary-foreground" />
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
              icon={<Play className="h-5 w-5 text-zinc-400" />}
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
        detailedContent={
          <>
            {useCase?.detailed_description && (
              <p className="leading-relaxed text-zinc-400">
                {useCase.detailed_description}
              </p>
            )}
            {communityWorkflow && (
              <div className="text-zinc-400">
                {communityWorkflow.description}
              </div>
            )}
          </>
        }
        steps={
          steps && steps.length > 0 ? (
            <div className="w-[400px] flex-shrink-0">
              <div className="sticky top-8 rounded-3xl bg-zinc-900 px-6 pt-4 pb-2">
                <div className="text-sm font-medium text-zinc-500">
                  Workflow Steps:
                </div>
                <WorkflowSteps steps={stepsFormatted || []} size="large" />
              </div>
            </div>
          ) : undefined
        }
      />
      <FinalSection />
    </>
  );
}
