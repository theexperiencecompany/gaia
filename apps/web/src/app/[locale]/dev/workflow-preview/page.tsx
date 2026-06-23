"use client";

import { Button } from "@heroui/button";
import { type ComponentProps, useState } from "react";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import WorkflowModal from "@/features/workflows/components/WorkflowModal";
import type { TriggerConfig } from "@/features/workflows/triggers/types";
import type { PublicWorkflowStep } from "@/types/features/workflowTypes";

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

type Scenario =
  | "create"
  | "create-steps"
  | "edit"
  | "edit-public"
  | "preview"
  | "trig-gmail"
  | "trig-calendar"
  | "trig-slack"
  | "trig-github";

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
};

export default function WorkflowPreviewPage() {
  const [scenario, setScenario] = useState<Scenario>("create");
  const [isOpen, setIsOpen] = useState(true);

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
