import WorkflowExecutionHistory from "../WorkflowExecutionHistory";

interface WorkflowExecutionPanelProps {
  workflowId: string;
}

export default function WorkflowExecutionPanel({
  workflowId,
}: WorkflowExecutionPanelProps) {
  return <WorkflowExecutionHistory workflowId={workflowId} />;
}
