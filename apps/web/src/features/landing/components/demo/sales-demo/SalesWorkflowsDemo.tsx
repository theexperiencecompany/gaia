import { WorkflowsDemoBase } from "../WorkflowsDemoBase";
import { SALES_WORKFLOW_CONFIG } from "../workflowsDemoData";

export function SalesWorkflowsDemo() {
  return <WorkflowsDemoBase {...SALES_WORKFLOW_CONFIG} />;
}
