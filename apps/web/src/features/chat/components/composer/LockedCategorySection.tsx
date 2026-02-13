import { Button } from "@heroui/button";
import { SquareLock01Icon } from "@icons";
import type React from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import type { SlashCommandMatch } from "../../hooks/useSlashCommands";

interface LockedCategorySectionProps {
  category: string;
  tools: SlashCommandMatch[];
  requiredIntegration: {
    id: string;
    name: string; // Display name from backend - single source of truth
  };
  onConnect?: () => void;
}

export const LockedCategorySection: React.FC<LockedCategorySectionProps> = ({
  tools,
  requiredIntegration,
  onConnect,
}) => {
  const { connectIntegration, integrations } = useIntegrations();

  const integration = integrations.find(
    (int) => int.id.toLowerCase() === requiredIntegration.id.toLowerCase(),
  );

  const handleConnect = async () => {
    try {
      await connectIntegration(requiredIntegration.id);
      onConnect?.();
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  const isConnected = integration?.status === "connected";

  return (
    <div className="mx-2 mt-4 mb-2">
      <div className="flex items-center justify-between rounded-xl bg-zinc-800 p-2">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-500/20">
            <SquareLock01Icon className="h-4 w-4 text-red-400" />
          </div>
          <div>
            <div className="text-sm font-medium text-zinc-200">
              {tools.length} {requiredIntegration.name} tools locked
            </div>
            <div className="text-xs text-zinc-500">
              Requires {requiredIntegration.name} connection
            </div>
          </div>
        </div>

        {!isConnected && (
          <Button
            size="sm"
            color="primary"
            variant="flat"
            startContent={getToolCategoryIcon(
              requiredIntegration.id,
              {
                size: 16,
                width: 16,
                height: 16,
                showBackground: false,
                className: "h-4 w-4 object-contain",
              },
              integration?.iconUrl,
            )}
            onPress={handleConnect}
          >
            Connect
          </Button>
        )}
      </div>
    </div>
  );
};
