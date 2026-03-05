import type { WorkflowStep } from "../WorkflowsDemoBase";
import { WorkflowsDemoBase } from "../WorkflowsDemoBase";

const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    id: "wf-1",
    label: "Scanning HubSpot pipeline",
    detail: "12 active deals",
    category: "hubspot",
  },
  {
    id: "wf-2",
    label: "Checking email threads",
    detail: "3 need follow-up",
    category: "gmail",
  },
  {
    id: "wf-3",
    label: "Pulling calendar",
    detail: "4 calls today",
    category: "googlecalendar",
  },
  {
    id: "wf-4",
    label: "Checking LinkedIn signals",
    detail: "2 job changes",
    category: "linkedin",
  },
  {
    id: "wf-5",
    label: "Posting brief to Slack",
    detail: "via #sales-team",
    category: "slack",
  },
];

export function SalesWorkflowsDemo() {
  return (
    <WorkflowsDemoBase
      title="Daily Pipeline Brief"
      schedule="Every day at 8:00 AM"
      steps={WORKFLOW_STEPS}
    />
  );
}
