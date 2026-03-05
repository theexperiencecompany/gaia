import type { ReactNode } from "react";
import type { WorkflowStep } from "./WorkflowsDemoBase";

export interface WorkflowsDemoConfig {
  title: string;
  schedule: string;
  steps: WorkflowStep[];
  fallbackIcon?: (isDone: boolean, isRunning: boolean) => ReactNode;
}

export const FOUNDERS_WORKFLOW_CONFIG: WorkflowsDemoConfig = {
  title: "Daily Founder Briefing",
  schedule: "Every day at 9:00 AM",
  steps: [
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
  ],
};

export const SALES_WORKFLOW_CONFIG: WorkflowsDemoConfig = {
  title: "Daily Pipeline Brief",
  schedule: "Every day at 8:00 AM",
  steps: [
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
  ],
};

export const PM_WORKFLOW_CONFIG: WorkflowsDemoConfig = {
  title: "Weekly Stakeholder Update",
  schedule: "Every Friday at 4:00 PM",
  steps: [
    {
      id: "wf-1",
      label: "Pulling sprint metrics",
      detail: "from Linear",
      category: "linear",
    },
    {
      id: "wf-2",
      label: "Fetching release notes",
      detail: "from GitHub",
      category: "github",
    },
    {
      id: "wf-3",
      label: "Reading roadmap context",
      detail: "from Notion",
      category: "notion",
    },
    {
      id: "wf-4",
      label: "Drafting update email",
      detail: "3 recipients",
      category: "gmail",
    },
    {
      id: "wf-5",
      label: "Posting summary to Slack",
      detail: "via #product",
      category: "slack",
    },
  ],
};

export const EM_WORKFLOW_CONFIG: WorkflowsDemoConfig = {
  title: "Weekly Team Health Report",
  schedule: "Every Friday at 5:00 PM",
  steps: [
    {
      id: "wf-1",
      label: "Pulling sprint velocity",
      detail: "from Linear",
      category: "linear",
    },
    {
      id: "wf-2",
      label: "Calculating PR cycle times",
      detail: "from GitHub",
      category: "github",
    },
    {
      id: "wf-3",
      label: "Checking team blockers",
      detail: "from Slack",
      category: "slack",
    },
    {
      id: "wf-4",
      label: "Building retro document",
      detail: "in Notion",
      category: "notion",
    },
    {
      id: "wf-5",
      label: "Posting report to Slack",
      detail: "via #engineering",
      category: "slack",
    },
  ],
};

export const SOFTWARE_DEV_WORKFLOW_CONFIG: WorkflowsDemoConfig = {
  title: "Dev Daily Briefing",
  schedule: "Every day at 9:00 AM",
  steps: [
    {
      id: "wf-1",
      label: "Checking merged PRs",
      detail: "3 merged yesterday",
      category: "github",
    },
    {
      id: "wf-2",
      label: "Loading Linear tickets",
      detail: "5 completed",
      category: "linear",
    },
    {
      id: "wf-3",
      label: "Scanning Slack threads",
      detail: "12 unread",
      category: "slack",
    },
    {
      id: "wf-4",
      label: "Checking calendar",
      detail: "2 meetings today",
      category: "googlecalendar",
    },
    {
      id: "wf-5",
      label: "Posting standup",
      detail: "via Slack",
      category: "slack",
    },
  ],
};

export const AGENCY_WORKFLOW_CONFIG: WorkflowsDemoConfig = {
  title: "Weekly Client Report — TechCorp",
  schedule: "Every Friday at 4:00 PM",
  steps: [
    {
      id: "wf-1",
      label: "Pulling project progress",
      detail: "from ClickUp",
      category: "clickup",
    },
    {
      id: "wf-2",
      label: "Fetching metrics data",
      detail: "from Sheets",
      category: "googlesheets",
    },
    {
      id: "wf-3",
      label: "Checking open items",
      detail: "from email",
      category: "gmail",
    },
    {
      id: "wf-4",
      label: "Drafting status report",
      detail: "8 clients",
      category: "gmail",
    },
    {
      id: "wf-5",
      label: "Notifying account team",
      detail: "via Slack",
      category: "slack",
    },
  ],
  fallbackIcon: () => (
    <div className="flex h-5.5 w-5.5 items-center justify-center rounded-full bg-purple-400/30">
      <div className="h-2 w-2 rounded-full bg-purple-400" />
    </div>
  ),
};
