import { Button } from "@heroui/button";
import { AlertCircleIcon, CheckmarkCircle02Icon } from "@icons";
import CustomSpinner from "@/components/ui/spinner";
import type { Workflow } from "../../api/workflowApi";
import WorkflowSteps from "../shared/WorkflowSteps";

interface WorkflowLoadingStateProps {
  phase: "creating" | "generating" | "error" | "success";
  mode: "create" | "edit" | "preview";
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
      <div className="flex min-h-[280px] flex-col items-center justify-center gap-4 py-8 text-center">
        <div className="rounded-full bg-danger/15 p-4">
          <AlertCircleIcon className="h-8 w-8 text-danger" />
        </div>
        <div>
          <h3 className="text-base font-semibold text-zinc-100">
            {mode === "create" ? "Couldn't create workflow" : "Couldn't update"}
          </h3>
          <p className="mt-1 max-w-sm text-sm text-zinc-400">
            {error ||
              `Something went wrong while ${mode === "create" ? "creating" : "updating"} the workflow.`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="light" onPress={onClose}>
            Cancel
          </Button>
          <Button color="primary" onPress={onRetry}>
            Try again
          </Button>
        </div>
      </div>
    );
  }

  if (phase === "creating" || phase === "generating") {
    return (
      <div className="flex min-h-[280px] flex-col items-center justify-center gap-4 py-8 text-center">
        <CustomSpinner variant="logo" />
        <div>
          <h3 className="text-base font-semibold text-zinc-100">
            {phase === "generating" ? "Generating steps" : "Creating workflow"}
          </h3>
          <p className="mt-1 text-sm text-zinc-400">
            {phase === "generating"
              ? "Building the plan for your workflow..."
              : "Setting things up and generating steps..."}
          </p>
        </div>
      </div>
    );
  }

  if (phase === "success") {
    return (
      <div className="flex flex-col gap-6 py-6">
        <div className="flex flex-col items-center justify-center gap-3 text-center">
          <div className="rounded-full bg-success/15 p-4">
            <CheckmarkCircle02Icon className="h-8 w-8 text-success" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-zinc-100">
              Workflow {mode === "create" ? "created" : "updated"}
            </h3>
            <p className="mt-1 text-sm text-zinc-400">
              "{workflow?.title || "Untitled Workflow"}" is ready to use
              {workflow?.steps?.length
                ? ` · ${workflow.steps.length} steps`
                : ""}
            </p>
          </div>
          <Button color="primary" variant="flat" onPress={onClose}>
            Done
          </Button>
        </div>

        {workflow?.steps && workflow.steps.length > 0 && (
          <div className="space-y-3">
            <h4 className="text-sm font-medium text-zinc-200">
              Generated steps
            </h4>
            <div className="max-h-48 overflow-y-auto rounded-2xl bg-zinc-900/60 p-3">
              <WorkflowSteps steps={workflow.steps} />
            </div>
          </div>
        )}
      </div>
    );
  }

  return null;
}
