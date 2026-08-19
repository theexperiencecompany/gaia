import { Button } from "@heroui/button";
import Link from "next/link";

interface EmptyStateProps {
  filteredUseCasesLength: number;
  selectedCategory: string | null;
  workflowsLength: number;
  isLoadingWorkflows: boolean;
}

export function UseCaseEmptyStates({
  filteredUseCasesLength,
  selectedCategory,
  workflowsLength,
  isLoadingWorkflows,
}: EmptyStateProps) {
  return (
    <>
      {filteredUseCasesLength === 0 &&
        selectedCategory !== null &&
        selectedCategory !== "workflows" && (
          <div className="flex h-48 items-center justify-center" />
        )}

      {selectedCategory === "workflows" &&
        !isLoadingWorkflows &&
        workflowsLength === 0 && (
          <div className="flex h-48 items-center justify-center">
            <div className="space-y-1 text-center">
              <p className="text-foreground-600 text-lg">No workflows found</p>
              <p className="text-foreground-400 mb-5 text-sm">
                Create your first workflow to get started
              </p>
              <Link href="/workflows">
                <Button color="primary">Create</Button>
              </Link>
            </div>
          </div>
        )}

      {selectedCategory === "workflows" && isLoadingWorkflows && (
        <div className="flex h-48 items-center justify-center">
          <div className="text-center">
            <p className="text-foreground-500 text-lg">Loading workflows...</p>
          </div>
        </div>
      )}
    </>
  );
}
