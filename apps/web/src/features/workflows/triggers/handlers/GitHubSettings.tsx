/**
 * GitHub Trigger Settings
 *
 * UI configuration for GitHub triggers: repository selection with infinite
 * scroll, or manual owner/repo entry.
 */

"use client";

import { Button } from "@heroui/button";
import { Select, SelectItem } from "@heroui/select";
import { useState } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { TriggerConnectionPrompt } from "../components/TriggerConnectionPrompt";
import {
  TriggerSettingRow,
  TriggerSettingsCard,
} from "../components/TriggerSettingsCard";
import { TriggerTagInput } from "../components/TriggerTagInput";
import { useInfiniteTriggerOptions } from "../hooks/useInfiniteTriggerOptions";
import {
  isTriggerOption,
  type TriggerOption,
} from "../hooks/useTriggerOptions";
import type { TriggerSettingsProps } from "../registry";
import type { TriggerConfigDraft } from "../types";

type GitHubTriggerData = {
  trigger_name: string;
  repos?: string[];
};

export interface GitHubConfig extends TriggerConfigDraft {
  trigger_name?: string;
  trigger_data?: GitHubTriggerData;
}

/** A repository, or the trailing "Loading more..." row while a page is fetched. */
type RepoItem = TriggerOption & { isLoader?: boolean };

const LOADER_ITEM: RepoItem = {
  value: "loading-more",
  label: "Loading more...",
  isLoader: true,
};

// Accepts "owner/repo" with valid GitHub name segments.
function isValidRepo(value: string): boolean {
  const parts = value.split("/");
  if (parts.length !== 2) return false;
  const [owner, repo] = parts;
  const githubNameRegex = /^[a-zA-Z0-9]([a-zA-Z0-9-_]*[a-zA-Z0-9])?$/;
  return githubNameRegex.test(owner) && githubNameRegex.test(repo);
}

export function GitHubSettings({
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

  const triggerSlug = config.trigger_name || "";

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useInfiniteTriggerOptions(
      integrationId,
      triggerSlug,
      "repo",
      isConnected && !!triggerSlug && !useManualInput,
    );

  const repoOptions: RepoItem[] = (data?.pages ?? [])
    .flat()
    .filter(isTriggerOption);

  const updateTriggerData = (updates: Partial<GitHubTriggerData>) => {
    const currentTriggerData = triggerData || {
      trigger_name: config.trigger_name || "",
    };

    // Prepare new data
    const newData = {
      ...currentTriggerData,
      ...updates,
    };

    onConfigChange({
      ...config,
      trigger_data: newData,
    });
  };

  const handleSelectionChange = (keys: "all" | Set<React.Key>) => {
    const selectedKeys = keys === "all" ? [] : Array.from(keys).map(String);

    updateTriggerData({
      repos: selectedKeys,
    });
  };

  // Fetch the next page once the listbox is scrolled to its bottom.
  const attachScrollLoader = (listbox: HTMLElement | null) => {
    if (!listbox) return;
    listbox.onscroll = () => {
      const bottom =
        listbox.scrollHeight - listbox.scrollTop === listbox.clientHeight;
      if (bottom && hasNextPage && !isFetchingNextPage) {
        fetchNextPage();
      }
    };
  };

  if (!isConnected) {
    return (
      <TriggerConnectionPrompt
        integrationName="GitHub"
        integrationId={integrationId}
        iconUrl={integrations.find((i) => i.id === integrationId)?.iconUrl}
        onConnect={() => connectIntegration(integrationId)}
      />
    );
  }

  const currentSelectedKeys = triggerData?.repos || [];

  return (
    <TriggerSettingsCard>
      <TriggerSettingRow label="Repositories" wide>
        {!useManualInput ? (
          <div className="space-y-2">
            <Select
              aria-label="Repositories"
              placeholder="Select repositories"
              selectionMode="multiple"
              selectedKeys={new Set(currentSelectedKeys)}
              onSelectionChange={handleSelectionChange}
              isLoading={isLoading}
              scrollRef={attachScrollLoader}
              className="w-full"
              items={hasNextPage ? [...repoOptions, LOADER_ITEM] : repoOptions}
              renderValue={(items) => {
                const count = items.filter(
                  (item) => item.key !== LOADER_ITEM.value,
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
                        {item.label}
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
          </div>
        ) : (
          <TriggerTagInput
            values={triggerData?.repos || []}
            onChange={(repos) => updateTriggerData({ repos })}
            validate={isValidRepo}
            prefix="github.com/"
            placeholder="octocat/hello-world"
            emptyPlaceholder="octocat/hello-world"
            description={
              <button
                type="button"
                onClick={() => setUseManualInput(false)}
                className="cursor-pointer font-medium text-primary hover:underline"
              >
                Back to list
              </button>
            }
          />
        )}
      </TriggerSettingRow>
    </TriggerSettingsCard>
  );
}
