/**
 * Grid of suggested workflow cards rendered inside the workflows stage.
 * Wraps the shared `UnifiedWorkflowCard` in a static (non-actionable) form.
 * Clicking a card fetches the real workflow and opens the shared
 * `WorkflowModal` in `preview` mode — same UI as edit, all fields disabled,
 * with a footer note pointing the user to the Workflows page for edits.
 */

"use client";

import * as m from "motion/react-m";
import dynamic from "next/dynamic";
import { memo, useCallback, useState } from "react";
import { workflowApi } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import type { Workflow } from "@/types/features/workflowTypes";
import { EASE_OUT_QUART } from "../constants/motion";

const WorkflowModal = dynamic(
  () => import("@/features/workflows/components/WorkflowModal"),
  { ssr: false },
);

interface OnboardingWorkflow {
  id?: string;
  title: string;
  description?: string;
  steps?: Array<{ category: string; title?: string; description?: string }>;
  trigger?: {
    type: string;
    cron_expression?: string;
    timezone?: string;
  };
}

interface OnboardingWorkflowCardsProps {
  workflows: OnboardingWorkflow[];
  embedded?: boolean;
}

function OnboardingWorkflowCardsImpl({
  workflows,
  embedded = false,
}: OnboardingWorkflowCardsProps) {
  const [activeWorkflow, setActiveWorkflow] = useState<Workflow | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const handleCardClick = useCallback(
    async (workflowId: string | undefined) => {
      if (loadingId) return;
      if (!workflowId) {
        console.error("[onboarding] Workflow card clicked with no id");
        return;
      }
      setLoadingId(workflowId);
      try {
        const response = await workflowApi.getWorkflow(workflowId);
        setActiveWorkflow(response.workflow);
        setIsOpen(true);
      } catch (err) {
        console.error("Failed to load workflow", err);
      } finally {
        setLoadingId(null);
      }
    },
    [loadingId],
  );

  const handleOpenChange = useCallback((open: boolean) => {
    setIsOpen(open);
    if (!open) setActiveWorkflow(null);
  }, []);

  return (
    <>
      <m.div
        className={
          embedded
            ? "grid grid-cols-1 gap-3 sm:grid-cols-2"
            : "ml-10.75 grid grid-cols-1 gap-3 sm:grid-cols-2"
        }
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3 }}
      >
        {workflows.map((workflow, index) => {
          const cardSteps =
            workflow.steps?.map((step, stepIndex) => ({
              id: `${workflow.id ?? index}-step-${stepIndex}`,
              category: step.category,
              title: step.title ?? "",
              description: step.description ?? "",
            })) ?? [];

          return (
            <m.div
              key={workflow.id ?? `workflow-${index}`}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: index * 0.08,
                duration: 0.35,
                ease: EASE_OUT_QUART,
              }}
            >
              <UnifiedWorkflowCard
                title={workflow.title}
                description={workflow.description}
                steps={cardSteps}
                primaryAction="none"
                showTrigger={false}
                showExecutions={false}
                showActivationStatus={false}
                onCardClick={() => handleCardClick(workflow.id)}
              />
            </m.div>
          );
        })}
      </m.div>

      <WorkflowModal
        isOpen={isOpen}
        onOpenChange={handleOpenChange}
        mode="preview"
        existingWorkflow={activeWorkflow}
      />
    </>
  );
}

export const OnboardingWorkflowCards = memo(OnboardingWorkflowCardsImpl);
