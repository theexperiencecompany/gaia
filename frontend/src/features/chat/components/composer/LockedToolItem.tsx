import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { ExternalLink, Lock } from "lucide-react";
import React from "react";

import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import { EnhancedToolInfo } from "../../types/enhancedTools";

interface LockedToolItemProps {
  tool: EnhancedToolInfo;
  onConnect?: () => void;
  showDescription?: boolean;
}

export const LockedToolItem: React.FC<LockedToolItemProps> = ({
  tool,
  onConnect,
  showDescription = true,
}) => {
  const { connectIntegration, integrations } = useIntegrations();

  // Find the integration for this tool
  const integration = integrations.find(
    (int) => int.id === tool.integration?.requiredIntegration,
  );

  const handleConnect = async () => {
    if (tool.integration?.requiredIntegration) {
      try {
        await connectIntegration(tool.integration.requiredIntegration);
        onConnect?.();
      } catch (error) {
        console.error("Failed to connect integration:", error);
      }
    }
  };

  const categoryIcon = getToolCategoryIcon(tool.category);

  return (
    <div className="group relative">
      {/* Locked Overlay */}
      <div className="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-zinc-900/80 backdrop-blur-sm">
        <div className="text-center">
          <div className="mx-auto mb-2 flex h-8 w-8 items-center justify-center rounded-full bg-zinc-800">
            <Lock className="h-4 w-4 text-zinc-400" />
          </div>
          <p className="text-xs text-zinc-400">Requires Connection</p>
        </div>
      </div>

      {/* Tool Item (blurred background) */}
      <div className="opacity-50 blur-[1px] filter">
        <div className="flex items-center gap-3 rounded-lg p-3 transition-colors">
          {/* Tool Icon */}
          <div className="flex h-8 w-8 items-center justify-center rounded-lg">
            {categoryIcon}
          </div>

          {/* Tool Info */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium text-zinc-200">
                {formatToolName(tool.name)}
              </span>
              <Chip
                size="sm"
                variant="flat"
                color="default"
                className="text-xs"
              >
                {tool.category}
              </Chip>
            </div>
            {showDescription && tool.integration?.description && (
              <p className="mt-1 text-xs text-zinc-500">
                {tool.integration.description}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Connect Button (appears on hover) */}
      <div className="absolute inset-x-0 bottom-2 z-20 opacity-0 transition-opacity group-hover:opacity-100">
        <div className="flex items-center justify-center">
          {integration && (
            <Button
              size="sm"
              color="primary"
              variant="flat"
              startContent={
                integration ? (
                  getToolCategoryIcon(integration.id, {
                    size: 16,
                    width: 16,
                    height: 16,
                    showBackground: false,
                    className: "h-4 w-4",
                  })
                ) : (
                  <ExternalLink className="h-4 w-4" />
                )
              }
              onClick={handleConnect}
              className="shadow-lg"
            >
              Connect {tool.integration?.integrationName}
            </Button>
          )}
        </div>
      </div>

      {/* Integration Status Indicator */}
      {tool.integration && (
        <div className="absolute top-2 right-2 z-20">
          <div className="flex items-center gap-1">
            <div className="h-2 w-2 rounded-full bg-red-500"></div>
            <span className="text-xs text-zinc-500">
              {tool.integration.integrationName}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
