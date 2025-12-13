import React from "react";

import type { Workflow } from "../api/workflowApi";
import WorkflowModal from "./WorkflowModal";

interface EditWorkflowModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onWorkflowUpdated?: (workflowId: string) => void;
  onWorkflowDeleted?: (workflowId: string) => void;
  onWorkflowListRefresh?: () => void;
  workflow: Workflow | null;
}

export default function EditWorkflowModal({
  isOpen,
  onOpenChange,
  onWorkflowUpdated,
  onWorkflowDeleted,
  onWorkflowListRefresh,
  workflow,
}: EditWorkflowModalProps) {
  return (
    <WorkflowModal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      onWorkflowSaved={onWorkflowUpdated}
      onWorkflowDeleted={onWorkflowDeleted}
      onWorkflowListRefresh={onWorkflowListRefresh}
      mode="edit"
      existingWorkflow={workflow}
    />
  );
}
