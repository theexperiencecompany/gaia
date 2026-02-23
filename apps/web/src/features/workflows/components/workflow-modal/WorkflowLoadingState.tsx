import { Button } from "@heroui/button";
import { AlertCircleIcon, CheckmarkCircle02Icon } from "@icons";
import CustomSpinner from "@/components/ui/spinner";
import type { Workflow } from "../../api/workflowApi";
import WorkflowSteps from "../shared/WorkflowSteps";

interface WorkflowLoadingStateProps {
  phase: "creating" | "generating" | "error" | "success";
  mode: "create" | "edit";
  error?: string | null;
  workflow?: Workflow | null;
  onClose: () => void;
  onRetry: () => void;
}

export default function WorkflowLoadingState({
  phase,
  mode,
  error,
  workflow,
  onClose,
  onRetry,
}: WorkflowLoadingStateProps) {
  if (phase === "error") {
    return (
      <div className="flex flex-col items-center justify-center space-y-4 py-8">
        <AlertCircleIcon className="h-12 w-12 text-danger" />
        <div className="text-center">
          <h3 className="text-lg font-medium text-danger">
            {mode === "create" ? "Creation" : "Update"} Failed
          </h3>
          <p className="text-sm text-zinc-400">
            {error ||
              `Something went wrong while ${mode === "create" ? "creating" : "updating"} the workflow`}
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="flat" onPress={onClose}>
            Cancel
          </Button>
          <Button color="primary" onPress={onRetry}>
            Try Again
          </Button>
        </div>
      </div>
    );
  }

  if (phase === "creating" || phase === "generating") {
    return (
      <div className="flex flex-col items-center justify-center space-y-4 py-8">
        <CustomSpinner variant="logo" />
        <div className="text-center">
          <h3 className="text-lg font-medium">
            {phase === "generating" ? "Generating Steps" : "Creating Workflow"}
          </h3>
          <p className="text-sm text-zinc-400">
            {phase === "generating"
              ? "Generating workflow steps..."
              : "Setting up your workflow and generating steps..."}
          </p>
        </div>
      </div>
    );
  }

  if (phase === "success") {
    return (
      <div className="flex flex-col space-y-6 py-6">
        <div className="flex flex-col items-center justify-center space-y-4">
          <CheckmarkCircle02Icon className="h-16 w-16 text-success" />
          <div className="text-center">
            <h3 className="text-lg font-medium text-success">
              Workflow {mode === "create" ? "Created" : "Updated"}!
            </h3>
            <p className="text-sm text-zinc-400">
              "{workflow?.title || "Untitled Workflow"}" is ready to use
            </p>
            {workflow && (
              <p className="mt-2 text-xs text-zinc-500">
                {workflow?.steps?.length || 0} steps generated
              </p>
            )}
          </div>
          <Button
            color="primary"
            variant="flat"
            onPress={onClose}
            className="mt-4"
          >
            Close
          </Button>
        </div>

        {/* Generated Steps Preview */}
        {workflow?.steps && workflow.steps.length > 0 && (
          <div className="space-y-3">
            <h4 className="text-sm font-medium text-zinc-300">
              Generated Steps:
            </h4>
            <div className="max-h-48 overflow-y-auto">
              <WorkflowSteps steps={workflow.steps} />
            </div>
          </div>
        )}
      </div>
    );
  }

  return null;
}
