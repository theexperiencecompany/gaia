import { useTransition } from "react";
import { handleAuthLogin } from "@/features/auth/hooks/handleAuthLogin";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { referralsApi } from "@/features/referrals/api/referralsApi";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";
import type { UseCase } from "@/types/features/workflowTypes";

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

/**
 * Creating the workflow behind a use case. A signed-out visitor signs in and
 * comes back to this page; a community workflow's creator is credited first.
 */
export function useCreateFromUseCase(
  useCase: UseCase | null,
  communityWorkflow: Workflow | null,
) {
  const [isCreating, startCreateTransition] = useTransition();
  const { createWorkflow } = useWorkflowCreation();
  const { selectWorkflow } = useWorkflowSelection();
  const { isAuthenticated } = useAuth();

  const handleCreateWorkflow = () => {
    if (!isAuthenticated) {
      startCreateTransition(async () => {
        if (communityWorkflow) {
          try {
            await referralsApi.creditWorkflow(communityWorkflow.id);
          } catch (error) {
            // The credit is a bonus for the creator; login never waits on it.
            console.error("Workflow credit error:", error);
          }
        }
        handleAuthLogin(window.location.pathname);
      });
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

  return { isCreating, handleCreateWorkflow };
}
