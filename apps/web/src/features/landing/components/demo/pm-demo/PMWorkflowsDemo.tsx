import { WorkflowsDemoBase } from "../WorkflowsDemoBase";
import { PM_WORKFLOW_CONFIG } from "../workflowsDemoData";

export function PMWorkflowsDemo() {
  return <WorkflowsDemoBase {...PM_WORKFLOW_CONFIG} />;
}
