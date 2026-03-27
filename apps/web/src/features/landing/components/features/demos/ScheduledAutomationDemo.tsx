"use client";

import type { WorkflowStep } from "@/features/landing/components/demo/WorkflowsDemoBase";
import { WorkflowsDemoBase } from "@/features/landing/components/demo/WorkflowsDemoBase";

const STEPS: WorkflowStep[] = [
  {
    id: "check-emails",
    label: "Check unread emails",
    detail: "Gmail",
    category: "email",
  },
  {
    id: "pull-calendar",
    label: "Pull calendar events",
    detail: "Google Calendar",
    category: "calendar",
  },
  {
    id: "fetch-slack",
    label: "Fetch Slack unread",
    detail: "Slack",
    category: "communication",
  },
  {
    id: "compile-summary",
    label: "Compile summary",
    detail: "AI",
    category: "ai",
  },
  {
    id: "send-email",
    label: "Send to email",
    detail: "Gmail",
    category: "email",
  },
];

export default function ScheduledAutomationDemo() {
  return (
    <WorkflowsDemoBase
      title="Daily Morning Digest"
      schedule="Every weekday at 8:00 AM"
      steps={STEPS}
    />
  );
}
