/**
 * GitHub Trigger Handler
 *
 * Handles UI configuration for GitHub triggers.
 */

import type { RegisteredHandler } from "../registry";
import type { TriggerConfig } from "../types";
import type { GitHubConfig } from "./GitHubSettings";
import { GitHubSettings } from "./GitHubSettings";

export const githubTriggerHandler: RegisteredHandler = {
  triggerSlugs: [
    "github_commit_event",
    "github_pr_event",
    "github_star_added",
    "github_issue_added",
  ],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: "integration",
    enabled: true,
    trigger_name: slug,
    trigger_data: {
      trigger_name: slug,
      repos: [],
    },
  }),

  SettingsComponent: GitHubSettings,

  getDisplayInfo: (config) => {
    const triggerSlug = (config as GitHubConfig).trigger_name || config.type;
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
};
