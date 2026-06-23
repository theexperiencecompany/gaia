"use client";

import { Button } from "@heroui/button";
import type { MyIntegrationItem } from "@shared/types";
import { useQueryClient } from "@tanstack/react-query";
import { type ComponentProps, useEffect, useState } from "react";
import { integrationKeys } from "@/features/integrations/api/queryKeys";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import WorkflowModal from "@/features/workflows/components/WorkflowModal";
import type { TriggerConfig } from "@/features/workflows/triggers/types";
import type { TriggerSchema } from "@/features/workflows/triggers/types/base";
import type { PublicWorkflowStep } from "@/types/features/workflowTypes";

// The preview runs without a backend, so the trigger-schema and "my
// integrations" endpoints fail. Seed both query caches with realistic mocks so
// the Event tab renders the trigger selector and its connected config instead
// of an endless skeleton.
const triggerSchema = (
  slug: string,
  integrationId: string,
  name: string,
  description: string,
): TriggerSchema => ({
  slug,
  composio_slug: slug.toUpperCase(),
  name,
  description,
  provider: integrationId,
  integration_id: integrationId,
  config_schema: {},
});

const MOCK_TRIGGER_SCHEMAS: TriggerSchema[] = [
  triggerSchema(
    "gmail_poll_inbox",
    "gmail",
    "New email in inbox",
    "Runs whenever new email arrives in your inbox.",
  ),
  triggerSchema(
    "calendar_event_starting_soon",
    "googlecalendar",
    "Event starting soon",
    "Runs shortly before a calendar event begins.",
  ),
  triggerSchema(
    "slack_new_message",
    "slack",
    "New Slack message",
    "Runs when a new message is posted in a channel.",
  ),
  triggerSchema(
    "github_commit_event",
    "github",
    "New commit",
    "Runs when a new commit is pushed to a repository.",
  ),
  triggerSchema(
    "linear_issue_created",
    "linear",
    "Issue created",
    "Runs when a new issue is created.",
  ),
  triggerSchema(
    "notion_new_page_in_db",
    "notion",
    "New database item",
    "Runs when a new item is added to a database.",
  ),
  triggerSchema(
    "asana_task_trigger",
    "asana",
    "Task added",
    "Runs when a task is added to a project.",
  ),
  triggerSchema(
    "google_sheets_new_row",
    "googlesheets",
    "New row added",
    "Runs when a row is added to a spreadsheet.",
  ),
];

const connectedIntegration = (id: string, name: string): MyIntegrationItem => ({
  id,
  name,
  description: `${name} integration`,
  category: "productivity",
  source: "platform",
  managedBy: "composio",
  status: "connected",
  requiresAuth: true,
  isFeatured: false,
  displayPriority: 0,
  available: true,
  toolCount: 5,
  cloneCount: 0,
  iconUrl: `/images/icons/${id}.webp`,
});

const MOCK_MY_INTEGRATIONS = {
  integrations: [
    connectedIntegration("gmail", "Gmail"),
    connectedIntegration("googlecalendar", "Google Calendar"),
    connectedIntegration("slack", "Slack"),
    connectedIntegration("github", "GitHub"),
    connectedIntegration("linear", "Linear"),
    connectedIntegration("notion", "Notion"),
    connectedIntegration("asana", "Asana"),
    connectedIntegration("googlesheets", "Google Sheets"),
  ],
  total: 8,
};

const MOCK_STEPS = [
  {
    id: "s1",
    title: "Fetch today's calendar events",
    category: "googlecalendar",
    description: "Pull every event for the day from the primary calendar.",
  },
  {
    id: "s2",
    title: "Scan unread priority emails",
    category: "gmail",
    description: "Find important unread emails from the last 24 hours.",
  },
  {
    id: "s3",
    title: "Compose the briefing",
    category: "gaia",
    description: "Summarize everything into a short, skimmable briefing.",
  },
  {
    id: "s4",
    title: "Deliver to your channels",
    category: "gaia",
    description: "Send the briefing to your connected channels.",
  },
];

const MOCK_WORKFLOW: Workflow = {
  id: "wf_preview",
  title: "Morning briefing",
  description: "A concise summary of my day, every morning.",
  prompt:
    "Every morning, gather my calendar events, unread important emails, and top headlines, then send me a concise briefing I can read in under a minute.",
  steps: MOCK_STEPS,
  trigger_config: {
    type: "schedule",
    enabled: true,
    cron_expression: "0 8 * * *",
    timezone: "America/New_York",
  },
  activated: true,
  notify_on_completion: true,
  user_id: "u_preview",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  current_step_index: 0,
  execution_logs: [],
  total_executions: 12,
  successful_executions: 11,
  is_public: false,
  is_system_workflow: false,
};

const MOCK_PUBLIC_WORKFLOW: Workflow = {
  ...MOCK_WORKFLOW,
  id: "wf_preview_public",
  is_public: true,
  slug: "morning-briefing",
  activated: false,
};

const PREDEFINED_STEPS: PublicWorkflowStep[] = MOCK_STEPS.map((s) => ({
  id: s.id,
  title: s.title,
  category: s.category,
  description: s.description,
}));

/** An edit-mode workflow pre-set to a specific event trigger config. */
function triggerWorkflow(
  id: string,
  title: string,
  triggerConfig: TriggerConfig,
): Workflow {
  return { ...MOCK_WORKFLOW, id, title, trigger_config: triggerConfig };
}

const GMAIL_POLL = triggerWorkflow("wf_gmail", "Inbox watcher", {
  type: "integration",
  enabled: true,
  trigger_name: "gmail_poll_inbox",
  trigger_data: { trigger_name: "gmail_poll_inbox", interval: 15 },
});

const CALENDAR_SOON = triggerWorkflow("wf_cal", "Pre-meeting prep", {
  type: "integration",
  enabled: true,
  trigger_name: "calendar_event_starting_soon",
  trigger_data: {
    trigger_name: "calendar_event_starting_soon",
    calendar_ids: ["primary"],
    minutes_before_start: 15,
    include_all_day: false,
  },
});

const SLACK_MESSAGE = triggerWorkflow("wf_slack", "Slack mention triage", {
  type: "integration",
  enabled: true,
  trigger_name: "slack_new_message",
  trigger_data: {
    trigger_name: "slack_new_message",
    channel_ids: [],
    exclude_bot_messages: true,
  },
});

const GITHUB_COMMIT = triggerWorkflow("wf_github", "Commit digest", {
  type: "integration",
  enabled: true,
  trigger_name: "github_commit_event",
  trigger_data: { trigger_name: "github_commit_event", repos: [] },
});

const LINEAR_ISSUE = triggerWorkflow("wf_linear", "Issue triage", {
  type: "integration",
  enabled: true,
  trigger_name: "linear_issue_created",
  trigger_data: { trigger_name: "linear_issue_created", team_id: "" },
});

const NOTION_ITEM = triggerWorkflow("wf_notion", "Doc watcher", {
  type: "integration",
  enabled: true,
  trigger_name: "notion_new_page_in_db",
  trigger_data: { trigger_name: "notion_new_page_in_db", database_ids: [] },
});

const ASANA_TASK = triggerWorkflow("wf_asana", "Task tracker", {
  type: "integration",
  enabled: true,
  trigger_name: "asana_task_trigger",
  trigger_data: { trigger_name: "asana_task_trigger" },
});

const SHEETS_ROW = triggerWorkflow("wf_sheets", "Row logger", {
  type: "integration",
  enabled: true,
  trigger_name: "google_sheets_new_row",
  trigger_data: {
    trigger_name: "google_sheets_new_row",
    spreadsheet_ids: [],
    sheet_names: [],
  },
});

type Scenario =
  | "create"
  | "create-steps"
  | "edit"
  | "edit-public"
  | "preview"
  | "trig-gmail"
  | "trig-calendar"
  | "trig-slack"
  | "trig-github"
  | "trig-linear"
  | "trig-notion"
  | "trig-asana"
  | "trig-sheets";

const SCENARIOS: { key: Scenario; label: string }[] = [
  { key: "create", label: "Create" },
  { key: "create-steps", label: "Create (community steps)" },
  { key: "edit", label: "Edit" },
  { key: "edit-public", label: "Edit (published)" },
  { key: "preview", label: "Preview" },
  { key: "trig-gmail", label: "Event · Gmail poll" },
  { key: "trig-calendar", label: "Event · Calendar" },
  { key: "trig-slack", label: "Event · Slack" },
  { key: "trig-github", label: "Event · GitHub" },
  { key: "trig-linear", label: "Event · Linear" },
  { key: "trig-notion", label: "Event · Notion" },
  { key: "trig-asana", label: "Event · Asana" },
  { key: "trig-sheets", label: "Event · Sheets" },
];

type ModalProps = Omit<
  ComponentProps<typeof WorkflowModal>,
  "isOpen" | "onOpenChange"
>;

const SCENARIO_PROPS: Record<Scenario, ModalProps> = {
  create: { mode: "create" },
  "create-steps": { mode: "create", predefinedSteps: PREDEFINED_STEPS },
  edit: { mode: "edit", existingWorkflow: MOCK_WORKFLOW },
  "edit-public": { mode: "edit", existingWorkflow: MOCK_PUBLIC_WORKFLOW },
  preview: { mode: "preview", existingWorkflow: MOCK_WORKFLOW },
  "trig-gmail": { mode: "edit", existingWorkflow: GMAIL_POLL },
  "trig-calendar": { mode: "edit", existingWorkflow: CALENDAR_SOON },
  "trig-slack": { mode: "edit", existingWorkflow: SLACK_MESSAGE },
  "trig-github": { mode: "edit", existingWorkflow: GITHUB_COMMIT },
  "trig-linear": { mode: "edit", existingWorkflow: LINEAR_ISSUE },
  "trig-notion": { mode: "edit", existingWorkflow: NOTION_ITEM },
  "trig-asana": { mode: "edit", existingWorkflow: ASANA_TASK },
  "trig-sheets": { mode: "edit", existingWorkflow: SHEETS_ROW },
};

export default function WorkflowPreviewPage() {
  const [scenario, setScenario] = useState<Scenario>("create");
  const [isOpen, setIsOpen] = useState(true);
  const queryClient = useQueryClient();

  // Prime the caches the trigger UI depends on so the preview is self-contained
  // (no backend required). A failed background refetch keeps this seeded data.
  useEffect(() => {
    queryClient.setQueryData(["triggerSchemas"], MOCK_TRIGGER_SCHEMAS);
    queryClient.setQueryData(integrationKeys.me, MOCK_MY_INTEGRATIONS);
  }, [queryClient]);

  const selectScenario = (next: Scenario) => {
    setScenario(next);
    setIsOpen(true);
  };

  return (
    <div className="min-h-screen bg-primary-bg p-6">
      <div className="mx-auto flex max-w-3xl flex-col gap-3">
        <h1 className="text-lg font-semibold text-white">
          Workflow modal preview
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          {SCENARIOS.map((s) => (
            <Button
              key={s.key}
              size="sm"
              variant={scenario === s.key ? "solid" : "flat"}
              color={scenario === s.key ? "primary" : "default"}
              onPress={() => selectScenario(s.key)}
            >
              {s.label}
            </Button>
          ))}
          <Button size="sm" variant="bordered" onPress={() => setIsOpen(true)}>
            Reopen modal
          </Button>
        </div>
      </div>

      <WorkflowModal
        key={scenario}
        isOpen={isOpen}
        onOpenChange={setIsOpen}
        {...SCENARIO_PROPS[scenario]}
      />
    </div>
  );
}
