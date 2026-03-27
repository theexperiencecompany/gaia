"use client";

import type { WorkflowStep } from "@/features/landing/components/demo/WorkflowsDemoBase";
import { WorkflowsDemoBase } from "@/features/landing/components/demo/WorkflowsDemoBase";

const STEPS: WorkflowStep[] = [
  {
    id: "fetch-prs",
    label: "Fetch open pull requests",
    detail: "GitHub",
    category: "github",
  },
  {
    id: "filter-prs",
    label: "Filter by review status",
    detail: "Needs review",
    category: "code",
  },
  {
    id: "summarize-prs",
    label: "Summarize with AI",
    detail: "AI",
    category: "ai",
  },
  {
    id: "post-slack",
    label: "Post to #engineering",
    detail: "Slack",
    category: "slack",
  },
];

export default function WorkflowsDemo() {
  return (
    <WorkflowsDemoBase
      title="GitHub PR Summary"
      schedule="Every Friday at 5pm"
      steps={STEPS}
    />
  );
}
