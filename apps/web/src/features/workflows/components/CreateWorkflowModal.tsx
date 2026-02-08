import type { WorkflowDraftData } from "@/types/features/toolDataTypes";

import WorkflowModal from "./WorkflowModal";

interface CreateWorkflowModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onWorkflowCreated?: () => void;
  /** Pre-fill form from AI-generated draft data */
  draftData?: WorkflowDraftData | null;
}

export default function CreateWorkflowModal({
  isOpen,
  onOpenChange,
  onWorkflowCreated,
  draftData,
}: CreateWorkflowModalProps) {
  return (
    <WorkflowModal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      onWorkflowSaved={
        onWorkflowCreated ? () => onWorkflowCreated() : undefined
      }
      mode="create"
      draftData={draftData}
    />
  );
}
