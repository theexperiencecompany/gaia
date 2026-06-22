"use client";

import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";

import { SidebarContent, SidebarHeader } from "@/components/ui/sidebar";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { IntegrationInstructionsEditor } from "@/features/integrations/components/IntegrationInstructionsEditor";
import { IntegrationRelatedWorkflows } from "@/features/integrations/components/IntegrationRelatedWorkflows";
import { useIntegrationOwnership } from "@/features/integrations/hooks/useIntegrationOwnership";
import { useIntegrationTools } from "@/features/integrations/hooks/useIntegrationTools";
import type { Integration } from "@/features/integrations/types";

import { IntegrationActions } from "./integration-sidebar/IntegrationActions";
import { IntegrationHeaderChips } from "./integration-sidebar/IntegrationHeaderChips";

// Placeholder chip widths shown while an integration's tools load (on-demand
// fetch or post-connect discovery). Distinct values double as React keys.
const TOOL_SKELETON_WIDTHS = ["w-24", "w-20", "w-28", "w-16", "w-32", "w-14"];

interface IntegrationSidebarProps {
  integration: Integration;
  onConnect: (
    integrationId: string,
  ) => Promise<{ status: string; toolsCount?: number }>;
  onDisconnect?: (integrationId: string) => void;
  onDelete?: (integrationId: string) => Promise<void>;
  onPublish?: (integrationId: string) => Promise<void>;
  onUnpublish?: (integrationId: string) => Promise<void>;
  category?: string;
  /** True while a just-finished connect is still discovering tools in the background. */
  isSettling?: boolean;
}

export const IntegrationSidebar: React.FC<IntegrationSidebarProps> = ({
  integration,
  onConnect,
  onDisconnect,
  onDelete,
  onPublish,
  onUnpublish,
  category,
  isSettling = false,
}) => {
  const isConnected = integration.status === "connected";
  const {
    tools: integrationTools,
    mentionNames: toolMentionNames,
    isLoading: isLoadingTools,
  } = useIntegrationTools(integration, category);
  const { isOwnIntegration, isForkedIntegration } =
    useIntegrationOwnership(integration);

  // Show the tool skeleton both on the initial on-demand fetch and while a
  // just-connected integration is still discovering tools in the background —
  // either way the list is empty and would otherwise flash in.
  const showToolsSkeleton =
    integrationTools.length === 0 && (isLoadingTools || isSettling);

  return (
    <div className="flex h-full max-h-[calc(100vh-60px)] flex-col px-5">
      <SidebarHeader>
        <div className="w-fit">
          {getToolCategoryIcon(
            integration.id,
            {
              size: 40,
              width: 40,
              height: 40,
              showBackground: false,
            },
            integration.iconUrl,
          )}
        </div>
        <div className="mb-0 mt-2 flex flex-col items-start gap-1">
          <IntegrationHeaderChips
            integration={integration}
            isConnected={isConnected}
            isOwnIntegration={isOwnIntegration}
            isForkedIntegration={isForkedIntegration}
          />

          <h1 className="text-2xl font-semibold text-zinc-100">
            {integration.name}
          </h1>

          <p className="text-sm leading-relaxed font-light text-zinc-400">
            {integration.description}
          </p>
        </div>

        <IntegrationActions
          integration={integration}
          isConnected={isConnected}
          onConnect={onConnect}
          onDisconnect={onDisconnect}
          onDelete={onDelete}
          onPublish={onPublish}
          onUnpublish={onUnpublish}
        />

        {isConnected && (
          <div className="mt-3">
            <IntegrationInstructionsEditor
              integration={integration}
              toolNames={toolMentionNames}
            />
          </div>
        )}
        {integrationTools.length > 0 && (
          <h2 className="mt-3 text-sm font-medium text-zinc-300 relative right-1">
            Available tools ({integrationTools.length})
          </h2>
        )}
        {showToolsSkeleton && (
          <h2 className="mt-3 text-sm font-medium text-zinc-300 relative right-1">
            {isSettling ? "Setting up tools" : "Available tools"}
          </h2>
        )}
      </SidebarHeader>

      <SidebarContent className="flex-1 min-h-0 flex flex-col overflow-hidden">
        {integrationTools.length > 0 && (
          <div className="flex-1 min-h-0 overflow-y-auto pb-2">
            <div className="flex flex-wrap gap-2 content-start">
              {integrationTools.map((tool) => (
                <Chip
                  key={tool.name}
                  variant="bordered"
                  color="default"
                  radius="full"
                  className="font-light border-1 text-zinc-300"
                >
                  {tool.label}
                </Chip>
              ))}
            </div>
          </div>
        )}
        {showToolsSkeleton && (
          <div className="flex-1 min-h-0 overflow-y-auto pb-2">
            <div className="flex flex-wrap gap-2 content-start">
              {TOOL_SKELETON_WIDTHS.map((width) => (
                <Skeleton key={width} className={`h-7 ${width} rounded-full`} />
              ))}
            </div>
          </div>
        )}

        <div className="shrink-0 pb-4">
          <IntegrationRelatedWorkflows integrationId={integration.id} />
        </div>
      </SidebarContent>
    </div>
  );
};
