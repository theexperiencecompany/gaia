import { WorkflowsDemoBase } from "../WorkflowsDemoBase";
import { EM_WORKFLOW_CONFIG } from "../workflowsDemoData";

export function EMWorkflowsDemo() {
  return <WorkflowsDemoBase {...EM_WORKFLOW_CONFIG} />;
}

export default EMWorkflowsDemo;
