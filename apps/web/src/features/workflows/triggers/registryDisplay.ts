/**
 * Trigger Display Registry (display-only, no handlers)
 *
 * Pure, static lookup for trigger display info (label, integrationId).
 * Safe to import from the landing tree — does NOT pull any handler code
 * (no React components, no HeroUI, no integration UI logic).
 *
 * Keep in sync with the handlers in ./handlers/*. When a handler's
 * `getDisplayInfo` output changes, update the corresponding entry here.
 */

import type { TriggerConfig } from "./types";

export interface TriggerDisplayInfo {
  label: string;
  integrationId: string | null;
}

interface TriggerDisplayEntry {
  triggerSlugs: string[];
  getDisplayInfo: (config: TriggerConfig) => TriggerDisplayInfo;
}

// =============================================================================
// DISPLAY ENTRIES (mirrors handlers/*.tsx getDisplayInfo, without React deps)
// =============================================================================

const displayEntries: TriggerDisplayEntry[] = [
  {
    triggerSlugs: ["asana_task_trigger"],
    getDisplayInfo: () => ({
      label: "on new task",
      integrationId: "asana",
    }),
  },
  {
    triggerSlugs: ["calendar_event_created", "calendar_event_starting_soon"],
    getDisplayInfo: (config) => {
      const triggerName =
        (config as { trigger_name?: string }).trigger_name || config.type;
      return {
        label:
          triggerName === "calendar_event_starting_soon"
            ? "event starting soon"
            : "on new calendar event",
        integrationId: "googlecalendar",
      };
    },
  },
  {
    triggerSlugs: [
      "github_commit_event",
      "github_pr_event",
      "github_star_added",
      "github_issue_added",
    ],
    getDisplayInfo: (config) => {
      const triggerSlug =
        (config as { trigger_name?: string }).trigger_name || config.type;
      const map = {
        github_commit_event: "on new commit",
        github_pr_event: "on PR update",
        github_star_added: "on new star",
        github_issue_added: "on new issue",
      };
      return {
        label: map[triggerSlug as keyof typeof map] || "on github event",
        integrationId: "github",
      };
    },
  },
  {
    triggerSlugs: ["gmail_new_message", "email", "gmail_poll_inbox"],
    getDisplayInfo: () => ({
      label: "on new emails",
      integrationId: "gmail",
    }),
  },
  {
    triggerSlugs: [
      "google_docs_new_document",
      "google_docs_document_deleted",
      "google_docs_document_updated",
    ],
    getDisplayInfo: (config) => {
      const triggerName =
        (config as { trigger_name?: string }).trigger_name || config.type;
      let label = "on new document";
      if (triggerName === "google_docs_document_deleted")
        label = "on document deleted";
      if (triggerName === "google_docs_document_updated")
        label = "on document updated";
      return {
        label,
        integrationId: "googledocs",
      };
    },
  },
  {
    triggerSlugs: ["google_sheets_new_row", "google_sheets_new_sheet"],
    getDisplayInfo: (config) => {
      const triggerName =
        (config as { trigger_name?: string }).trigger_name || config.type;
      return {
        label:
          triggerName === "google_sheets_new_row"
            ? "on new row"
            : "on new sheet",
        integrationId: "googlesheets",
      };
    },
  },
  {
    triggerSlugs: [
      "linear_issue_created",
      "linear_issue_updated",
      "linear_comment_added",
    ],
    getDisplayInfo: (config) => {
      const triggerName =
        (config as { trigger_name?: string }).trigger_name || config.type;
      let label = "on linear event";
      if (triggerName === "linear_issue_created") label = "on new issue";
      if (triggerName === "linear_issue_updated") label = "on issue updated";
      if (triggerName === "linear_comment_added") label = "on new comment";
      return {
        label,
        integrationId: "linear",
      };
    },
  },
  {
    triggerSlugs: ["manual"],
    getDisplayInfo: () => ({
      label: "manual trigger",
      integrationId: null,
    }),
  },
  {
    triggerSlugs: [
      "notion_new_page_in_db",
      "notion_page_updated",
      "notion_all_page_events",
    ],
    getDisplayInfo: (config) => {
      const triggerName =
        (config as { trigger_name?: string }).trigger_name || config.type;
      let label = "on notion event";
      if (triggerName === "notion_new_page_in_db") label = "on new page in db";
      if (triggerName === "notion_page_updated") label = "on page updated";
      if (triggerName === "notion_all_page_events") label = "on any page event";
      return {
        label,
        integrationId: "notion",
      };
    },
  },
  {
    triggerSlugs: ["schedule"],
    getDisplayInfo: () => ({
      label: "scheduled",
      integrationId: null,
    }),
  },
  {
    triggerSlugs: ["slack_new_message", "slack_channel_created"],
    getDisplayInfo: (config) => {
      const triggerName =
        (config as { trigger_name?: string }).trigger_name || config.type;
      return {
        label:
          triggerName === "slack_channel_created"
            ? "on channel created"
            : "on new message",
        integrationId: "slack",
      };
    },
  },
  {
    triggerSlugs: ["todoist_new_task_created"],
    getDisplayInfo: () => ({
      label: "on new task",
      integrationId: "todoist",
    }),
  },
];

// =============================================================================
// LOOKUP
// =============================================================================

const slugToDisplayEntry = new Map<string, TriggerDisplayEntry>();
for (const entry of displayEntries) {
  for (const slug of entry.triggerSlugs) {
    slugToDisplayEntry.set(slug, entry);
  }
}

export function getTriggerDisplayInfoBySlug(
  slug: string,
  config: TriggerConfig,
): TriggerDisplayInfo | undefined {
  const entry = slugToDisplayEntry.get(slug);
  if (!entry) return undefined;
  return entry.getDisplayInfo(config);
}
