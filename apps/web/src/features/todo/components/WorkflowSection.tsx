"use client";

import { useEffect, useState } from "react";

import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { todoApi } from "@/features/todo/api/todoApi";
import {
  WorkflowEmptyState,
  WorkflowHeader,
  WorkflowLoadingState,
  WorkflowSteps,
} from "@/features/workflows/components";
import { WorkflowStatus } from "@/types/features/todoTypes";
import type { Workflow as WorkflowType } from "@/types/features/workflowTypes";

interface WorkflowSectionProps {
  workflow?: WorkflowType;
  isGenerating?: boolean;
  workflowStatus?: WorkflowStatus;
  todoId: string;
  onGenerateWorkflow?: () => void;
  onWorkflowGenerated?: (workflow: WorkflowType) => void;
  newWorkflow?: WorkflowType; // Direct workflow update prop
}

export default function WorkflowSection({
  workflow: initialWorkflow,
  isGenerating = false,
  workflowStatus: initialWorkflowStatus = WorkflowStatus.NOT_STARTED,
  todoId,
  onGenerateWorkflow,
  onWorkflowGenerated,
  newWorkflow,
}: WorkflowSectionProps) {
  const [workflow, setWorkflow] = useState<WorkflowType | undefined>(
    initialWorkflow,
  );
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus>(
    initialWorkflowStatus,
  );
  const [localIsGenerating, setLocalIsGenerating] = useState(
    isGenerating || workflowStatus === WorkflowStatus.GENERATING,
  );

  const { selectWorkflow } = useWorkflowSelection();

  // Fetch workflow on component mount and when refresh is triggered
  useEffect(() => {
    const fetchWorkflow = async () => {
      try {
        const status = await todoApi.getWorkflowStatus(todoId);
        if (status.has_workflow && status.workflow) {
          setWorkflow(status.workflow);
          setWorkflowStatus(status.workflow_status);
        } else {
          setWorkflow(undefined);
          setWorkflowStatus(WorkflowStatus.NOT_STARTED);
        }
      } catch (error) {
        console.error("Failed to fetch workflow:", error);
      }
    };

    fetchWorkflow();
  }, [todoId]);

  // Handle direct workflow updates (for instant updates after generation)
  useEffect(() => {
    if (!newWorkflow) return;
    setWorkflow(newWorkflow);
    setWorkflowStatus(WorkflowStatus.COMPLETED);
    setLocalIsGenerating(false); // Ensure we stop generating state
    onWorkflowGenerated?.(newWorkflow);
  }, [newWorkflow, onWorkflowGenerated]);

  // Poll for workflow completion when generating
  useEffect(() => {
    if (!localIsGenerating || workflow) return;

    const pollInterval = setInterval(async () => {
      try {
        const status = await todoApi.getWorkflowStatus(todoId);

        if (status.has_workflow && status.workflow) {
          setLocalIsGenerating(false);
          setWorkflow(status.workflow);
          setWorkflowStatus(status.workflow_status);
          onWorkflowGenerated?.(status.workflow);
          clearInterval(pollInterval);
        } else if (status.workflow_status === WorkflowStatus.FAILED) {
          setLocalIsGenerating(false);
          setWorkflowStatus(WorkflowStatus.FAILED);
          clearInterval(pollInterval);
          console.error("Workflow generation failed");
        }
      } catch (error) {
        console.error("Failed to check workflow status:", error);
      }
    }, 5000); // Poll every 5 seconds

    // Cleanup after 60 seconds to prevent infinite polling
    const timeoutId = setTimeout(() => {
      setLocalIsGenerating(false);
      clearInterval(pollInterval);
      console.warn("Workflow generation timed out");
    }, 60000);

    return () => {
      clearInterval(pollInterval);
      clearTimeout(timeoutId);
    };
  }, [localIsGenerating, workflow, todoId, onWorkflowGenerated]);

  // Update local generating state when props change
  useEffect(() => {
    setLocalIsGenerating(
      isGenerating || workflowStatus === WorkflowStatus.GENERATING,
    );
  }, [isGenerating, workflowStatus]);

  const handleRunWorkflow = async () => {
    if (!workflow) return;

    try {
      // Convert the todo workflow to the expected format
      const workflowData = {
        id: workflow.id,
        title: workflow.title,
        description: workflow.description,
        steps: workflow.steps.map(
          (step: {
            id: string;
            title: string;
            description: string;
            category: string;
          }) => ({
            id: step.id,
            title: step.title,
            description: step.description,
            category: step.category,
          }),
        ),
      };

      selectWorkflow(workflowData, { autoSend: true });

      console.log(
        "Workflow selected for manual execution in chat with auto-send",
      );
    } catch (error) {
      console.error("Failed to select workflow for execution:", error);
    }
  };

  if (localIsGenerating) {
    return <WorkflowLoadingState />;
  }

  if (!workflow) {
    return <WorkflowEmptyState onGenerateWorkflow={onGenerateWorkflow} />;
  }

  return (
    <div className="space-y-2">
      <WorkflowHeader
        onGenerateWorkflow={onGenerateWorkflow}
        onRunWorkflow={handleRunWorkflow}
      />
      <WorkflowSteps key={workflow.id} steps={workflow.steps} />
    </div>
  );
}
