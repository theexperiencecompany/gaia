/**
 * GitHub Trigger Handler
 *
 * Handles UI configuration for GitHub triggers.
 */

"use client";

import { Button } from "@heroui/button";
import { Select, SelectItem } from "@heroui/select";
import { useState } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useInfiniteTriggerOptions } from "../hooks/useInfiniteTriggerOptions";
import type { RegisteredHandler, TriggerSettingsProps } from "../registry";
import type { TriggerConfig } from "../types";

// =============================================================================
// GITHUB SETTINGS COMPONENT
// =============================================================================

interface GitHubConfig extends TriggerConfig {
  owner?: string;
  repo?: string;
  repos?: string[]; // Multi-select support
  trigger_slug?: string;
}

interface RepoOption {
  value: string;
  label: string;
  owner?: string;
  isLoader?: boolean;
}

function GitHubSettings({
  triggerConfig,
  onConfigChange,
}: TriggerSettingsProps) {
  const { integrations, connectIntegration } = useIntegrations();
  // Config fields
  const config = triggerConfig as GitHubConfig;
  const integrationId = "github";

  const isConnected =
    integrations.find((i) => i.id === integrationId)?.status === "connected";

  const [useManualInput, setUseManualInput] = useState(false);
  const [tagInput, setTagInput] = useState("");

  const triggerSlug = (config.trigger_slug || config.type) ?? "";

  // Infinite Query for pagination
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useInfiniteTriggerOptions(
      integrationId,
      triggerSlug,
      "repo",
      isConnected && !!triggerSlug && !useManualInput,
    );

  // Flatten pages
  const repoOptions = (data?.pages.flat() || []) as RepoOption[];

  const handleSelectionChange = (keys: "all" | Set<React.Key>) => {
    // keys is a Set of strings
    const selectedKeys = keys === "all" ? [] : Array.from(keys).map(String);

    // Update config with array of repos
    onConfigChange({
      ...config,
      repos: selectedKeys,
      // Backward compatibility: set first repo as 'repo' and its owner
      repo: selectedKeys[0] || "",
      owner: selectedKeys[0] ? selectedKeys[0].split("/")[0] : "",
    });
  };

  const handleAddTag = () => {
    const trimmed = tagInput.trim();
    if (!trimmed) return;

    // Comprehensive validation for owner/repo format
    // Must be: owner/repo where both parts are valid GitHub identifiers

    // Check for exactly one slash and no leading/trailing slashes
    if (trimmed.startsWith("/") || trimmed.endsWith("/")) {
      // Invalid: starts or ends with slash
      return;
    }

    const parts = trimmed.split("/");
    if (parts.length !== 2) {
      // Invalid: must have exactly one slash
      return;
    }

    const [owner, repo] = parts;

    // Both owner and repo must be non-empty
    if (!owner || !repo) {
      return;
    }

    // GitHub username/repo validation: alphanumeric, hyphens, underscores
    // Cannot start with hyphen
    const githubNameRegex = /^[a-zA-Z0-9]([a-zA-Z0-9-_]*[a-zA-Z0-9])?$/;

    if (!githubNameRegex.test(owner) || !githubNameRegex.test(repo)) {
      // Invalid characters or format
      return;
    }

    const currentRepos = config.repos || [];
    if (!currentRepos.includes(trimmed)) {
      const updatedRepos = [...currentRepos, trimmed];
      onConfigChange({
        ...config,
        repos: updatedRepos,
        repo: updatedRepos[0] || "",
        owner: updatedRepos[0] ? updatedRepos[0].split("/")[0] : "",
      });
    }
    setTagInput("");
  };

  const handleRemoveTag = (repoToRemove: string) => {
    const currentRepos = config.repos || [];
    const updatedRepos = currentRepos.filter((r) => r !== repoToRemove);
    onConfigChange({
      ...config,
      repos: updatedRepos,
      repo: updatedRepos[0] || "",
      owner: updatedRepos[0] ? updatedRepos[0].split("/")[0] : "",
    });
  };

  const handleTagInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleAddTag();
    } else if (
      e.key === "Backspace" &&
      !tagInput &&
      config.repos &&
      config.repos.length > 0
    ) {
      // Remove last tag on backspace if input is empty
      handleRemoveTag(config.repos[config.repos.length - 1]);
    }
  };

  const handleScroll = (e: React.UIEvent<HTMLUListElement>) => {
    const bottom =
      e.currentTarget.scrollHeight - e.currentTarget.scrollTop ===
      e.currentTarget.clientHeight;
    if (bottom && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  };

  if (!isConnected) {
    return (
      <div className="flex flex-col items-center justify-center p-4 space-y-3 bg-zinc-900/50 rounded-lg border border-zinc-800">
        <p className="text-sm text-zinc-400">
          Connect GitHub to configure this trigger
        </p>
        <Button
          color="primary"
          variant="flat"
          onPress={() => connectIntegration(integrationId)}
        >
          Connect GitHub
        </Button>
      </div>
    );
  }

  // Determine current selected keys
  // Prefer `repos` array if present, else fallback to `repo` string wrapped in array
  const currentSelectedKeys =
    config.repos && config.repos.length > 0
      ? config.repos
      : config.repo
        ? [config.repo]
        : [];

  return (
    <div className="space-y-3">
      {!useManualInput ? (
        <>
          <Select
            label="Repositories"
            placeholder="Select repositories"
            selectionMode="multiple"
            selectedKeys={new Set(currentSelectedKeys)}
            onSelectionChange={handleSelectionChange}
            isLoading={isLoading}
            scrollRef={(ref) => {
              if (ref) {
                ref.onscroll =
                  handleScroll as unknown as GlobalEventHandlers["onscroll"];
              }
            }}
            className="w-full max-w-xl"
            items={[
              ...repoOptions,
              ...(hasNextPage
                ? [
                    {
                      value: "loading-more",
                      label: "Loading more...",
                      isLoader: true,
                    },
                  ]
                : []),
            ]}
            renderValue={(items) => {
              const count = items.filter(
                (item) => item.key !== "loading-more",
              ).length;
              if (count === 0) return "Select repositories";
              if (count === 1) return items[0]?.textValue || "1 repository";
              return `${count} repositories selected`;
            }}
            description={
              <div className="flex justify-between items-center">
                <span className="text-xs text-zinc-500">
                  {repoOptions.length} loaded
                </span>
                <button
                  type="button"
                  onClick={() => setUseManualInput(true)}
                  className="text-xs text-primary hover:underline cursor-pointer"
                >
                  Or enter manually
                </button>
              </div>
            }
          >
            {(item) => (
              <SelectItem
                key={item.value}
                textValue={item.label}
                isReadOnly={item.isLoader}
                className={item.isLoader ? "h-unit-8" : ""}
              >
                {item.isLoader ? (
                  <div className="flex justify-center w-full">
                    <span className="text-xs text-zinc-500">
                      Loading more...
                    </span>
                  </div>
                ) : (
                  item.label
                )}
              </SelectItem>
            )}
          </Select>
          {/* Load more button if not using scroll listener effectively inside Select */}
          {hasNextPage && !isLoading && (
            <Button
              size="sm"
              variant="light"
              className="w-full text-xs"
              onPress={() => fetchNextPage()}
              isLoading={isFetchingNextPage}
            >
              Load more repositories
            </Button>
          )}
        </>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-col gap-2">
            <label
              htmlFor="github-repo-input"
              className="text-sm font-medium text-zinc-300"
            >
              Repositories
            </label>
            <div className="relative group max-w-xl">
              <div className="flex flex-wrap gap-2 p-3 border-2 border-zinc-700/50 rounded-lg bg-gradient-to-br from-zinc-900 to-zinc-900/80 min-h-[52px] transition-all duration-200 focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/20 hover:border-zinc-600/50">
                {config.repos?.map((repo) => (
                  <span
                    key={repo}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gradient-to-br from-zinc-800 to-zinc-800/80 text-zinc-100 rounded-md border border-zinc-700/50 shadow-sm hover:shadow-md hover:border-zinc-600 transition-all duration-200 group/tag"
                  >
                    <span className="font-mono text-xs">{repo}</span>
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(repo)}
                      className="ml-0.5 text-zinc-400 hover:text-red-400 hover:bg-red-500/10 rounded px-1 transition-all duration-200 group-hover/tag:text-zinc-300"
                      aria-label={`Remove ${repo}`}
                    >
                      <svg
                        className="w-3.5 h-3.5"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M6 18L18 6M6 6l12 12"
                        />
                      </svg>
                    </button>
                  </span>
                ))}
                <input
                  id="github-repo-input"
                  type="text"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={handleTagInputKeyDown}
                  onBlur={handleAddTag}
                  placeholder={
                    config.repos && config.repos.length > 0
                      ? "Add another..."
                      : "e.g., octocat/hello-world"
                  }
                  className="flex-1 min-w-[160px] bg-transparent outline-none text-sm text-zinc-100 placeholder-zinc-500/70"
                />
              </div>
            </div>
            <div className="flex items-center justify-between text-xs text-zinc-500 px-1">
              <span className="flex items-center gap-2">
                Press{" "}
                <kbd className="px-2 py-1 bg-zinc-800/80 border border-zinc-700/50 rounded shadow-sm font-mono text-zinc-400">
                  Space
                </kbd>{" "}
                or{" "}
                <kbd className="px-2 py-1 bg-zinc-800/80 border border-zinc-700/50 rounded shadow-sm font-mono text-zinc-400">
                  Enter
                </kbd>{" "}
                to add
              </span>
              <button
                type="button"
                onClick={() => setUseManualInput(false)}
                className="text-primary/90 hover:text-primary font-medium hover:underline cursor-pointer transition-colors ml-auto"
              >
                Back to list
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// HANDLER DEFINITION
// =============================================================================

export const githubTriggerHandler: RegisteredHandler = {
  triggerSlugs: [
    "github_commit_event",
    "github_pr_event",
    "github_star_added",
    "github_issue_added",
  ],

  createDefaultConfig: (slug: string): TriggerConfig => ({
    type: slug,
    enabled: true,
    owner: "",
    repo: "",
  }),

  SettingsComponent: GitHubSettings,

  getDisplayInfo: (config) => {
    const map = {
      github_commit_event: "on new commit",
      github_pr_event: "on PR update",
      github_star_added: "on new star",
      github_issue_added: "on new issue",
    };
    return {
      label: map[config.type as keyof typeof map] || "on github event",
      integrationId: "github",
    };
  },
};
