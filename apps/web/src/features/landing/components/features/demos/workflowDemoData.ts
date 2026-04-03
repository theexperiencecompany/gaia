import type { WorkflowStep } from "../../demo/WorkflowsDemoBase";

interface WorkflowDemoConfig {
  title: string;
  schedule: string;
  steps: WorkflowStep[];
}

export const WORKFLOW_DEMO_CONFIGS: Record<string, WorkflowDemoConfig> = {
  workflows: {
    title: "GitHub PR Summary",
    schedule: "Every Friday at 5pm",
    steps: [
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
    ],
  },
  "scheduled-automation": {
    title: "Daily Morning Digest",
    schedule: "Every weekday at 8:00 AM",
    steps: [
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
    ],
  },
  "event-triggers": {
    title: "New Email → Create Task",
    schedule: "Triggered: New Gmail email received",
    steps: [
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
    ],
  },
};
