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
// TYPE DEFINITIONS
// =============================================================================

interface GitHubTriggerData {
  trigger_name: string;
  owner?: string;
  repo?: string;
  repos?: string[];
}

interface GitHubConfig extends TriggerConfig {
  trigger_name?: string;
  trigger_data?: GitHubTriggerData;
}

// =============================================================================
// GITHUB SETTINGS COMPONENT
// =============================================================================

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
  const config = triggerConfig as GitHubConfig;
  const triggerData = config.trigger_data;
  const integrationId = "github";

  const isConnected =
    integrations.find((i) => i.id === integrationId)?.status === "connected";

  const [useManualInput, setUseManualInput] = useState(false);
  const [tagInput, setTagInput] = useState("");

  const triggerSlug = config.trigger_name || "";

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

  const updateTriggerData = (updates: Partial<GitHubTriggerData>) => {
    const currentTriggerData = triggerData || {
      trigger_name: config.trigger_name || "",
    };
    onConfigChange({
      ...config,
      trigger_data: {
        ...currentTriggerData,
        ...updates,
      },
    });
  };

  const handleSelectionChange = (keys: "all" | Set<React.Key>) => {
    const selectedKeys = keys === "all" ? [] : Array.from(keys).map(String);

    updateTriggerData({
      repos: selectedKeys,
      repo: selectedKeys[0] || "",
      owner: selectedKeys[0] ? selectedKeys[0].split("/")[0] : "",
    });
  };

  const handleAddTag = () => {
    const trimmed = tagInput.trim();
    if (!trimmed) return;

    if (trimmed.startsWith("/") || trimmed.endsWith("/")) {
      return;
    }

    const parts = trimmed.split("/");
    if (parts.length !== 2) {
      return;
    }

    const [owner, repo] = parts;

    if (!owner || !repo) {
      return;
    }

    const githubNameRegex = /^[a-zA-Z0-9]([a-zA-Z0-9-_]*[a-zA-Z0-9])?$/;

    if (!githubNameRegex.test(owner) || !githubNameRegex.test(repo)) {
      return;
    }

    const currentRepos = triggerData?.repos || [];
    if (!currentRepos.includes(trimmed)) {
      const updatedRepos = [...currentRepos, trimmed];
      updateTriggerData({
        repos: updatedRepos,
        repo: updatedRepos[0] || "",
        owner: updatedRepos[0] ? updatedRepos[0].split("/")[0] : "",
      });
    }
    setTagInput("");
  };

  const handleRemoveTag = (repoToRemove: string) => {
    const currentRepos = triggerData?.repos || [];
    const updatedRepos = currentRepos.filter((r) => r !== repoToRemove);
    updateTriggerData({
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
      triggerData?.repos &&
      triggerData.repos.length > 0
    ) {
      handleRemoveTag(triggerData.repos[triggerData.repos.length - 1]);
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

  const currentSelectedKeys =
    triggerData?.repos && triggerData.repos.length > 0
      ? triggerData.repos
      : triggerData?.repo
        ? [triggerData.repo]
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
                {triggerData?.repos?.map((repo) => (
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
                    triggerData?.repos && triggerData.repos.length > 0
                      ? "Add another..."
                      : "e.g., octocat/hello-world"
                  }
                  className="flex-1 min-w-[160px] bg-transparent outline-none text-sm text-zinc-100 placeholder-zinc-500/70"
                />
              </div>
            </div>
            <div className="flex items-center justify-between text-xs text-zinc-500 px-1 max-w-xl">
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
    type: "app",
    enabled: true,
    trigger_name: slug,
    trigger_data: {
      trigger_name: slug,
      owner: "",
      repo: "",
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
