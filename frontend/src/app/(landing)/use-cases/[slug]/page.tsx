"use client";

import { Avatar } from "@heroui/avatar";
import { Clock, Play, User } from "lucide-react";
import { notFound } from "next/navigation";
import { useEffect, useState } from "react";

import Spinner from "@/components/ui/shadcn/spinner";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import MetaInfoCard from "@/features/use-cases/components/MetaInfoCard";
import ToolsList from "@/features/use-cases/components/ToolsList";
import UseCaseDetailLayout from "@/features/use-cases/components/UseCaseDetailLayout";
import YouMightAlsoLike from "@/features/use-cases/components/YouMightAlsoLike";
import {
  useCasesData,
  type UseCase,
} from "@/features/use-cases/constants/dummy-data";
import { Workflow, workflowApi } from "@/features/workflows/api/workflowApi";
import WorkflowSteps from "@/features/workflows/components/shared/WorkflowSteps";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";
import { getTriggerDisplay } from "@/features/workflows/utils/triggerDisplay";
import { extractToolsFromSteps } from "@/features/workflows/utils/workflowUtils";

interface PageProps {
  params: Promise<{ slug: string }>;
}

/**
 * Use Case Detail Page
 *
 * This page handles both static use cases and dynamic community workflows:
 * 1. First attempts to find the slug in static useCasesData
 * 2. If not found, attempts to fetch from API as a community workflow
 * 3. Displays appropriate content based on the data source
 */
export default function UseCaseDetailPage({ params }: PageProps) {
  const [slug, setSlug] = useState<string>("");
  const [useCase, setUseCase] = useState<UseCase | null>(null);
  const [communityWorkflow, setCommunityWorkflow] = useState<Workflow | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const { createWorkflow } = useWorkflowCreation();
  const { selectWorkflow } = useWorkflowSelection();
  const { integrations } = useIntegrations();
  useEffect(() => {
    const fetchData = async () => {
      const resolvedParams = await params;
      setSlug(resolvedParams.slug);

      // First, check static data
      const staticUseCase = useCasesData.find(
        (uc) => uc.slug === resolvedParams.slug,
      );

      if (staticUseCase) {
        setUseCase(staticUseCase);
        setIsLoading(false);
        return;
      }

      // If not found in static data, try API as community workflow
      try {
        const response = await workflowApi.getWorkflow(resolvedParams.slug);
        const workflow = response.workflow;

        // If it's a public workflow, try to get it from community endpoint to get creator info
        if (workflow.is_public) {
          try {
            const communityResponse = await workflowApi.getCommunityWorkflows(
              100,
              0,
            );
            const communityWorkflow = communityResponse.workflows.find(
              (w) => w.id === workflow.id,
            );

            if (communityWorkflow) {
              // Merge the community workflow data (which has creator) with the full workflow data
              setCommunityWorkflow({
                ...workflow,
                creator: communityWorkflow.creator,
              });
            } else {
              setCommunityWorkflow(workflow);
            }
          } catch (error) {
            console.error("Error fetching community workflow details:", error);
            setCommunityWorkflow(workflow);
          }
        } else {
          setCommunityWorkflow(workflow);
        }

        setIsLoading(false);
      } catch (error) {
        console.error("Error fetching workflow:", error);
        // Not found in either location
        notFound();
      }
    };

    fetchData();
  }, [params]);

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

  if (isLoading) {
    return (
      <div className="flex min-h-screen w-screen items-center justify-center bg-gradient-to-b from-zinc-950 to-black">
        <Spinner />
      </div>
    );
  }

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

  // Prepare tools
  const tools =
    useCase?.tools || extractToolsFromSteps(communityWorkflow?.steps || []);

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
                  triggerInfo.icon ? (
                    <img
                      src={triggerInfo.icon}
                      alt="Trigger"
                      className="h-5 w-5 object-contain"
                    />
                  ) : (
                    <Clock className="h-5 w-5 text-zinc-400" />
                  )
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
        similarContent={<YouMightAlsoLike currentSlug={currentSlug} />}
      />
      <FinalSection />
    </>
  );
}
