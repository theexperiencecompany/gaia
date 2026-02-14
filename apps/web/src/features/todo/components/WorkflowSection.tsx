"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/react";
import { PlayIcon, SparklesIcon, UndoIcon, ZapIcon } from "@icons";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { todoApi } from "@/features/todo/api/todoApi";
import { useTodoWorkflowWebSocket } from "@/features/todo/hooks/useTodoWorkflowWebSocket";
import { WorkflowSteps } from "@/features/workflows/components";
import { useTodoStore } from "@/stores/todoStore";
import type { Workflow as WorkflowType } from "@/types/features/workflowTypes";

interface WorkflowSectionProps {
  hideBg?: boolean;
  todoId: string;
  onWorkflowLinked?: (workflowId: string) => void;
}

/**
 * Unified WorkflowSection with consistent layout across all states.
 * Same header, conditionally rendered content.
 */
export default function WorkflowSection({
  hideBg,
  todoId,
  onWorkflowLinked,
}: WorkflowSectionProps) {
  const [workflow, setWorkflow] = useState<WorkflowType | undefined>();
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { selectWorkflow } = useWorkflowSelection();

  // WebSocket handlers
  const handleWorkflowGenerated = useCallback(
    (wf: WorkflowType) => {
      console.log("[WorkflowSection] WebSocket received workflow:", wf);
      setWorkflow(wf);
      setIsGenerating(false);
      setError(null);
      onWorkflowLinked?.(wf.id);

      // Sync categories to global store so todo item updates immediately
      const categories = [
        ...new Set(
          wf.steps.map((s) => s.category).filter((c): c is string => !!c),
        ),
      ].slice(0, 3);

      useTodoStore.getState().updateTodoOptimistic(todoId, {
        workflow_categories: categories,
      });

      toast.success("Workflow generated!");
    },
    [onWorkflowLinked, todoId],
  );

  const handleWorkflowFailed = useCallback((errorMsg: string) => {
    console.log("[WorkflowSection] WebSocket workflow failed:", errorMsg);
    setIsGenerating(false);
    setError(errorMsg);
    toast.error("Failed to generate workflow");
  }, []);

  useTodoWorkflowWebSocket({
    todoId,
    onWorkflowGenerated: handleWorkflowGenerated,
    onWorkflowFailed: handleWorkflowFailed,
  });

  // Fetch on mount
  useEffect(() => {
    const fetchWorkflow = async () => {
      try {
        const status = await todoApi.getWorkflowStatus(todoId);
        if (status.is_generating) {
          setIsGenerating(true);
        } else if (status.has_workflow && status.workflow) {
          setWorkflow(status.workflow);
        }
      } catch (err) {
        console.error("Failed to fetch workflow:", err);
      }
    };
    fetchWorkflow();
  }, [todoId]);

  // Generate workflow
  const handleGenerate = useCallback(async () => {
    if (isGenerating) return;
    setIsGenerating(true);
    setError(null);

    try {
      const result = await todoApi.generateWorkflow(todoId);
      if (result.status === "exists" && result.workflow) {
        setWorkflow(result.workflow);
        setIsGenerating(false);
        onWorkflowLinked?.(result.workflow.id);
        toast.info("Workflow already exists");
      } else if (result.status === "generating") {
        toast.success("Generating workflow...");
      }
    } catch (err) {
      setIsGenerating(false);
      setError(err instanceof Error ? err.message : "Unknown error");
      toast.error("Failed to start workflow generation");
    }
  }, [todoId, isGenerating, onWorkflowLinked]);

  // Run workflow
  const handleRun = useCallback(() => {
    if (!workflow) return;
    try {
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
  }, [workflow, selectWorkflow]);

  const hasWorkflow = !!workflow;

  return (
    <div className="space-y-3">
      {/* Consistent header for all states */}
      <div className="flex w-full items-center justify-between">
        <div className="flex items-center gap-1 w-full">
          <ZapIcon width={16} height={16} className="text-zinc-400" />
          <h3 className="text-sm font-normal text-zinc-400">
            Suggested Workflow
          </h3>
          {isGenerating && (
            <span className="flex items-center gap-1 text-xs text-primary ml-auto">
              <SparklesIcon className="h-3 w-3 animate-pulse" />
              Generating...
            </span>
          )}
        </div>

        {/* Actions - only show when has workflow or error */}
        {(hasWorkflow || error) && (
          <div className="flex items-center gap-2">
            <Tooltip content="Regenerate" color="foreground">
              <Button
                color="default"
                variant="flat"
                size="sm"
                onPress={handleGenerate}
                isIconOnly
                isDisabled={isGenerating}
              >
                <UndoIcon
                  className={`h-4 w-4 text-zinc-400 ${isGenerating ? "animate-spin" : ""}`}
                />
              </Button>
            </Tooltip>
            {hasWorkflow && (
              <Button
                color="success"
                variant="flat"
                size="sm"
                onPress={handleRun}
                isDisabled={isGenerating}
                endContent={<PlayIcon className="h-4 w-4" />}
              >
                Run
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Content - conditionally rendered based on state */}
      <div
        className={
          hideBg
            ? "border-0! bg-transparent! shadow-0! outline-0!"
            : "border-zinc-700 bg-zinc-800"
        }
      >
        <div>
          {isGenerating ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-start gap-3">
                  <Skeleton className="mt-1 h-6 w-6 rounded-full bg-zinc-600" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-40 bg-zinc-600" />
                    <Skeleton className="h-3 w-32 bg-zinc-600" />
                  </div>
                </div>
              ))}
            </div>
          ) : hasWorkflow ? (
            <WorkflowSteps steps={workflow.steps} />
          ) : (
            <div className="space-y-4 py-4 text-center">
              <div className="text-zinc-400">
                <SparklesIcon className="mx-auto mb-2 h-8 w-8 text-zinc-500" />
                {error ? (
                  <p className="text-sm text-red-400">
                    Generation failed. Try again?
                  </p>
                ) : (
                  <p className="text-sm">No workflow generated yet</p>
                )}
              </div>
              <Button
                color="primary"
                variant="flat"
                size="sm"
                onPress={handleGenerate}
                startContent={<SparklesIcon className="h-4 w-4" />}
              >
                {error ? "Retry" : "Generate Workflow"}
              </Button>
              <p className="mx-auto max-w-sm text-xs text-zinc-500">
                AI will create a step-by-step workflow to help complete this
                todo
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
