import { Button } from "@heroui/button";
import { Lock } from "lucide-react";
import React from "react";

import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import { SlashCommandMatch } from "../../hooks/useSlashCommands";

interface LockedCategorySectionProps {
  category: string;
  tools: SlashCommandMatch[];
  requiredIntegration: {
    id: string;
    name: string;
  };
  onConnect?: () => void;
}

export const LockedCategorySection: React.FC<LockedCategorySectionProps> = ({
  category,
  tools,
  requiredIntegration,
  onConnect,
}) => {
  const { connectIntegration, integrations } = useIntegrations();

  // Find the integration
  const integration = integrations.find(
    (int) => int.id === requiredIntegration.id,
  );

  const handleConnect = async () => {
    try {
      await connectIntegration(requiredIntegration.id);
      onConnect?.();
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  return (
    <div className="mx-2 mb-3">
      {/* Clean Connect Section */}
      <div className="sticky top-0 z-[4] mb-2 flex items-center justify-between rounded-lg bg-zinc-800 p-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-500/20">
            <Lock className="h-4 w-4 text-red-400" />
          </div>
          <div>
            <div className="text-sm font-medium text-zinc-200">
              {tools.length} {category.replace("_", " ")} tools locked
            </div>
            <div className="text-xs text-zinc-500">
              Requires {requiredIntegration.name} connection
            </div>
          </div>
        </div>

        {integration && (
          <Button
            size="sm"
            color="primary"
            variant="flat"
            startContent={getToolCategoryIcon(integration.id, {
              size: 16,
              width: 16,
              height: 16,
              showBackground: false,
              className: "h-4 w-4 object-contain",
            })}
            onPress={handleConnect}
          >
            Connect
          </Button>
        )}
      </div>

      {/* Disabled Tools List - Same design as normal tools with overlay */}
      <div className="relative z-[1] space-y-1">
        {tools.map((tool) => (
          <div key={tool.tool.name} className="relative">
            {/* Overlay */}
            <div className="absolute inset-0 z-10 rounded-xl bg-zinc-900/60 backdrop-blur-[1px]" />

            {/* Same design as normal tools */}
            <div className="relative mx-0 mb-1 rounded-xl border border-transparent p-3">
              <div className="flex items-center gap-3">
                {/* Icon */}
                <div className="flex-shrink-0">
                  {getToolCategoryIcon(tool.tool.category)}
                </div>

                {/* Content */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm text-foreground-600">
                      {formatToolName(tool.tool.name)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
