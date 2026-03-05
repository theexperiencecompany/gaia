import type { WorkflowStep } from "../WorkflowsDemoBase";
import { WorkflowsDemoBase } from "../WorkflowsDemoBase";

const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    id: "wf-1",
    label: "Scanning inbox",
    detail: "4 urgent emails",
    category: "gmail",
  },
  {
    id: "wf-2",
    label: "Loading calendar",
    detail: "3 meetings today",
    category: "googlecalendar",
  },
  {
    id: "wf-3",
    label: "Pulling metrics",
    detail: "MRR, churn, pipeline",
    category: "googlesheets",
  },
  {
    id: "wf-4",
    label: "Checking GitHub",
    detail: "2 open PRs",
    category: "github",
  },
  {
    id: "wf-5",
    label: "Posting briefing",
    detail: "via Slack",
    category: "slack",
  },
];

export default function WorkflowsDemo() {
  return (
    <WorkflowsDemoBase
      title="Daily Founder Briefing"
      schedule="Every day at 9:00 AM"
      steps={WORKFLOW_STEPS}
    />
  );
}
