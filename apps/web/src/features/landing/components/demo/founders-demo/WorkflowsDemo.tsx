import { WorkflowsDemoBase } from "../WorkflowsDemoBase";
import { FOUNDERS_WORKFLOW_CONFIG } from "../workflowsDemoData";

export default function WorkflowsDemo() {
  return <WorkflowsDemoBase {...FOUNDERS_WORKFLOW_CONFIG} />;
}
