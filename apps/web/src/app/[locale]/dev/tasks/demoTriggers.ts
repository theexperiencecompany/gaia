import type { TriggerData } from "./taskModel";

/**
 * The app events a task can start on: the API's workflow trigger schemas
 * (slug and app), named the way they read beside the app's logo, with the
 * settings each schema's trigger_data takes (apps/api/app/models/trigger_configs.py).
 */

/** Pick from the app's own list (GET /triggers/options); stored as ids in trigger_data[key]. */
interface PickSetting {
  kind: "pick";
  key: string;
  label: string;
  /** One choice (Linear's team_id) or several (repos, calendar_ids, channel_ids). */
  isMultiple: boolean;
  /** How an empty choice reads where the schema treats it as all (calendars, channels, teams). */
  allLabel?: string;
  /** Illustrative options; the real list comes from the connected account. */
  options: { id: string; label: string }[];
}

/** A number of minutes from a short list, as IntervalPicker offers them. */
interface MinutesSetting {
  kind: "minutes";
  key: string;
  label: string;
  choices: number[];
  initial: number;
}

interface ToggleSetting {
  kind: "toggle";
  key: string;
  label: string;
}

export type TriggerSetting = PickSetting | MinutesSetting | ToggleSetting;

export interface DemoTrigger {
  slug: string;
  app: string;
  name: string;
  settings?: TriggerSetting[];
}

const REPOS: PickSetting = {
  kind: "pick",
  key: "repos",
  label: "Repositories",
  isMultiple: true,
  options: [
    { id: "theexperiencecompany/gaia", label: "gaia" },
    { id: "theexperiencecompany/gaia-infra", label: "gaia-infra" },
    { id: "theexperiencecompany/internal-docs", label: "internal-docs" },
  ],
};

const CALENDARS: PickSetting = {
  kind: "pick",
  key: "calendar_ids",
  label: "Calendars",
  isMultiple: true,
  allLabel: "All calendars",
  options: [
    { id: "primary", label: "Personal" },
    { id: "work", label: "Work" },
    { id: "family", label: "Family" },
  ],
};

const LINEAR_TEAM: PickSetting = {
  kind: "pick",
  key: "team_id",
  label: "Team",
  isMultiple: false,
  allLabel: "All teams",
  options: [
    { id: "eng", label: "Engineering" },
    { id: "design", label: "Design" },
  ],
};

export const DEMO_TRIGGERS: DemoTrigger[] = [
  { slug: "gmail_new_message", app: "gmail", name: "New email" },
  { slug: "gmail_email_sent", app: "gmail", name: "Email sent" },
  { slug: "gmail_poll_inbox", app: "gmail", name: "New emails in inbox" },
  {
    slug: "calendar_event_created",
    app: "googlecalendar",
    name: "New event",
    settings: [CALENDARS],
  },
  {
    slug: "calendar_event_starting_soon",
    app: "googlecalendar",
    name: "Event starting soon",
    settings: [
      {
        kind: "minutes",
        key: "minutes_before_start",
        label: "How early",
        choices: [5, 10, 15, 30, 60],
        initial: 10,
      },
      CALENDARS,
      { kind: "toggle", key: "include_all_day", label: "All-day events" },
    ],
  },
  {
    slug: "github_pr_event",
    app: "github",
    name: "Pull request updated",
    settings: [REPOS],
  },
  {
    slug: "github_issue_added",
    app: "github",
    name: "New issue",
    settings: [REPOS],
  },
  {
    slug: "github_commit_event",
    app: "github",
    name: "New commit",
    settings: [REPOS],
  },
  {
    slug: "linear_issue_created",
    app: "linear",
    name: "New issue",
    settings: [LINEAR_TEAM],
  },
  {
    slug: "linear_issue_updated",
    app: "linear",
    name: "Issue updated",
    settings: [LINEAR_TEAM],
  },
  {
    slug: "linear_comment_added",
    app: "linear",
    name: "New comment",
    settings: [LINEAR_TEAM],
  },
  {
    slug: "slack_new_message",
    app: "slack",
    name: "New message",
    settings: [
      {
        kind: "pick",
        key: "channel_ids",
        label: "Channels",
        isMultiple: true,
        allLabel: "All channels",
        options: [
          { id: "C01", label: "#team" },
          { id: "C02", label: "#launch" },
          { id: "C03", label: "#random" },
        ],
      },
      { kind: "toggle", key: "exclude_bot_messages", label: "Skip bots" },
      {
        kind: "toggle",
        key: "exclude_thread_replies",
        label: "Skip thread replies",
      },
    ],
  },
  { slug: "notion_new_page_in_db", app: "notion", name: "New page" },
  { slug: "notion_page_updated", app: "notion", name: "Page updated" },
  { slug: "google_sheets_new_row", app: "googlesheets", name: "New row" },
  {
    slug: "google_docs_new_document",
    app: "googledocs",
    name: "New document",
  },
  { slug: "todoist_new_task_created", app: "todoist", name: "New task" },
];

/** A fresh event's settings, as the trigger handler's createDefaultConfig fills them. */
export function defaultTriggerData(trigger: DemoTrigger): TriggerData {
  const data: TriggerData = {};
  for (const setting of trigger.settings ?? []) {
    if (setting.kind === "pick")
      data[setting.key] = setting.isMultiple ? [] : "";
    if (setting.kind === "minutes") data[setting.key] = setting.initial;
    if (setting.kind === "toggle") data[setting.key] = false;
  }
  return data;
}
