"use client";

import type { WorkflowStep } from "../../demo/WorkflowsDemoBase";
import { WorkflowsDemoBase } from "../../demo/WorkflowsDemoBase";

const STEPS: WorkflowStep[] = [
  {
    id: "gmail-trigger",
    label: "Receive Gmail trigger",
    detail: "trigger",
    category: "gmail",
  },
  {
    id: "parse-email",
    label: "Parse email content",
    detail: "extract",
    category: "gmail",
  },
  {
    id: "extract-actions",
    label: "Extract action items",
    detail: "analyze",
    category: "workflow",
  },
  {
    id: "create-task",
    label: "Create task in Todos",
    detail: "write",
    category: "todoist",
  },
  {
    id: "notify-slack",
    label: "Notify via Slack",
    detail: "send",
    category: "slack",
  },
];

export default function EventTriggersDemo() {
  return (
    <WorkflowsDemoBase
      title="New Email → Create Task"
      schedule="Triggered: New Gmail email received"
      steps={STEPS}
    />
  );
}
