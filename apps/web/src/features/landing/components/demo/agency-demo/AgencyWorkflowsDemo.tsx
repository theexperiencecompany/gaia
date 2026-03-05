import { WorkflowsDemoBase } from "../WorkflowsDemoBase";
import { AGENCY_WORKFLOW_CONFIG } from "../workflowsDemoData";

export function AgencyWorkflowsDemo() {
  return <WorkflowsDemoBase {...AGENCY_WORKFLOW_CONFIG} />;
}
