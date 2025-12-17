import WorkflowModal from "./WorkflowModal";

interface CreateWorkflowModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onWorkflowCreated?: () => void;
  onWorkflowListRefresh?: () => void;
}

export default function CreateWorkflowModal({
  isOpen,
  onOpenChange,
  onWorkflowCreated,
  onWorkflowListRefresh,
}: CreateWorkflowModalProps) {
  return (
    <WorkflowModal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      onWorkflowSaved={
        onWorkflowCreated ? () => onWorkflowCreated() : undefined
      }
      onWorkflowListRefresh={onWorkflowListRefresh}
      mode="create"
    />
  );
}
