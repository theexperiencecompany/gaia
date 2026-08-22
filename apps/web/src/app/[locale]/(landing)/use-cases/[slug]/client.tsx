"use client";

import { PlayIcon, UserCircle02Icon } from "@icons";
import { getToolDisplayName } from "@shared/icons";
import { formatCompactNumber } from "@shared/utils";
import Image from "next/image";
import { useTransition } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationLookup } from "@/features/integrations/hooks/useIntegrationLookup";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import MetaInfoCard from "@/features/use-cases/components/MetaInfoCard";
import ToolsList from "@/features/use-cases/components/ToolsList";
import UseCaseDetailLayout from "@/features/use-cases/components/UseCaseDetailLayout";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import WorkflowSteps from "@/features/workflows/components/shared/WorkflowSteps";
import {
  DEFAULT_WORKFLOW_ICON_COLOR,
  WORKFLOW_ICON_BG_ALPHA,
  WORKFLOW_ICON_MAP,
} from "@/features/workflows/constants/workflowIconCatalog";
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
    icon: useCase?.icon ?? communityWorkflow?.icon ?? undefined,
    icon_color:
      useCase?.icon_color ?? communityWorkflow?.icon_color ?? undefined,
    // Reproduce the advertised trigger; manual only as a fallback.
    trigger_config: useCase?.trigger_config ??
      communityWorkflow?.trigger_config ?? {
        type: "manual" as const,
        enabled: true,
      },
    system_workflow_key:
      useCase?.system_workflow_key ??
      communityWorkflow?.system_workflow_key ??
      undefined,
    // Pass formatted steps if available to avoid regeneration
    ...(formattedSteps &&
      formattedSteps.length > 0 && {
        steps: formattedSteps,
      }),
    // Only generate if no steps exist
    generate_immediately: !formattedSteps || formattedSteps.length === 0,
  };
}

/** The workflow's chosen icon, on its own tinted tile, beside the page title. */
function renderHeroIcon(
  icon: string | null | undefined,
  iconColor: string | null | undefined,
) {
  const def = icon ? WORKFLOW_ICON_MAP.get(icon) : undefined;
  if (!def) return undefined;
  const color = iconColor ?? DEFAULT_WORKFLOW_ICON_COLOR;
  return (
    <div
      className="flex size-12 shrink-0 items-center justify-center rounded-xl"
      style={{ backgroundColor: `${color}${WORKFLOW_ICON_BG_ALPHA}` }}
    >
      <def.Icon size={26} style={{ color }} />
    </div>
  );
}

function deriveCreatorInfo(
  communityWorkflow: Workflow | null,
  useCase: UseCase | null,
) {
  if (!communityWorkflow && useCase?.creator) {
    return {
      creatorName: useCase.creator.name,
      creatorAvatar: resolveCreatorAvatar(useCase.creator),
      showCreator: true,
    };
  }

  // Explore cards carry a creator (the GAIA team by default) just like community
  // ones — without this the built-in and curated pages showed no author at all.

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
    showCreator: !!creatorName,
  };
}

function deriveRunCountText(
  communityWorkflow: Workflow | null,
  useCase: UseCase | null,
) {
  const runCount = communityWorkflow
    ? communityWorkflow.metadata?.total_executions ||
      communityWorkflow.total_executions ||
      0
    : (useCase?.total_executions ?? 0);
  if (runCount === 0) return "Never";
  return formatCompactNumber(runCount);
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

interface UseCaseMetaInfoProps {
  showCreator: boolean;
  creatorName?: string;
  creatorAvatar?: string;
  tools: Array<{ name: string; category: string }>;
  sourceIntegration?: string | null;
  integrationLabel?: string;
  runCountText: string;
  triggerInfo: { label: string; integrationId?: string } | null;
}

/** The chip row under the title: author, tools, provenance, runs, trigger. */
function UseCaseMetaInfo({
  showCreator,
  creatorName,
  creatorAvatar,
  tools,
  sourceIntegration,
  integrationLabel,
  runCountText,
  triggerInfo,
}: UseCaseMetaInfoProps) {
  return (
    <>
      {showCreator && (
        <MetaInfoCard
          icon={
            <div className="flex h-6 w-6 shrink-0 items-center justify-center overflow-hidden rounded-full">
              {creatorAvatar ? (
                <Image
                  src={creatorAvatar}
                  alt={creatorName ?? "Creator"}
                  width={100}
                  height={100}
                  className="object-contain"
                />
              ) : (
                <UserCircle02Icon className="h-6 w-6 text-zinc-300" />
              )}
            </div>
          }
          label="Created by"
          value={creatorName}
        />
      )}

      {tools.length > 0 && <ToolsList tools={tools} />}

      {sourceIntegration && (
        <MetaInfoCard
          icon={getToolCategoryIcon(sourceIntegration, {
            size: 28,
            width: 28,
            height: 28,
            showBackground: false,
          })}
          label="Included with"
          value={integrationLabel}
        />
      )}

      <MetaInfoCard
        icon={<PlayIcon className="h-7 w-7 text-zinc-400" />}
        label="Total runs"
        value={runCountText}
      />

      {triggerInfo && (
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
  );
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
  const { getIntegrationName } = useIntegrationLookup();

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
  const workflowPrompt = useCase?.prompt || communityWorkflow?.prompt;
  const sourceIntegration =
    useCase?.source_integration ?? communityWorkflow?.source_integration;
  const heroIcon = renderHeroIcon(data.icon, data.icon_color);
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

  const { creatorName, creatorAvatar, showCreator } = deriveCreatorInfo(
    communityWorkflow,
    useCase,
  );

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

  const runCountText = deriveRunCountText(communityWorkflow, useCase);

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
        icon={heroIcon}
        id={currentSlug}
        isCreating={isCreating}
        onCreateWorkflow={handleCreateWorkflow}
        metaInfo={
          <UseCaseMetaInfo
            showCreator={showCreator}
            creatorName={creatorName}
            creatorAvatar={creatorAvatar}
            tools={tools}
            sourceIntegration={sourceIntegration}
            integrationLabel={
              sourceIntegration
                ? (getIntegrationName(sourceIntegration) ??
                  getToolDisplayName(sourceIntegration))
                : undefined
            }
            runCountText={runCountText}
            triggerInfo={shouldShowTrigger ? triggerInfo : null}
          />
        }
        detailedContent={
          workflowPrompt ? (
            <div className="h-full rounded-3xl bg-zinc-900 p-6">
              <div className="mb-2 text-sm font-medium text-zinc-500">
                Prompt
              </div>
              <p className="whitespace-pre-wrap text-zinc-300">
                {workflowPrompt}
              </p>
            </div>
          ) : undefined
        }
        description={
          useCase?.detailed_description ||
          useCase?.description ||
          communityWorkflow?.description
        }
        steps={
          steps && steps.length > 0 ? (
            <div className="w-fit shrink-0">
              <div className="sticky top-8 rounded-3xl bg-zinc-900 p-6 pb-2">
                <div className="mb-2 text-sm font-medium text-zinc-500">
                  Steps
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
