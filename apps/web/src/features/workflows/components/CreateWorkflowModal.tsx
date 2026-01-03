import WorkflowModal from "./WorkflowModal";

interface CreateWorkflowModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onWorkflowCreated?: () => void;
}

export default function CreateWorkflowModal({
  isOpen,
  onOpenChange,
  onWorkflowCreated,
}: CreateWorkflowModalProps) {
  return (
    <WorkflowModal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      onWorkflowSaved={
        onWorkflowCreated ? () => onWorkflowCreated() : undefined
      }
      mode="create"
    />
  );
}
