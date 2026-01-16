import { shuffle } from "lodash";
import type React from "react";
import { useMemo } from "react";

import { Button, ChevronRight } from "@/components";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface Integration {
  id: string;
  name: string;
}

interface IntegrationsBannerProps {
  integrations: Integration[];
  isLoading: boolean;
  hasMessages: boolean;
  onToggleSlashCommand: () => void;
}

const IntegrationsBanner: React.FC<IntegrationsBannerProps> = ({
  integrations,
  isLoading,
  hasMessages,
  onToggleSlashCommand,
}) => {
  // Memoize shuffled integrations to prevent re-shuffling on every render
  const shuffledIntegrations = useMemo(
    () => shuffle(integrations),
    [integrations],
  );

  // Don't render if loading, no integrations, or if there are already messages
  if (isLoading || integrations.length === 0 || hasMessages) {
    return null;
  }

  return (
    <Button
      className="absolute -top-8 z-0 flex h-fit w-full bg-transparent! shadow-none"
      onClick={onToggleSlashCommand}
    >
      <div className="flex w-[90%] items-center justify-between rounded-full bg-surface-200/40 pr-4 pl-6 py-2 pb-9 text-xs text-foreground-300 hover:bg-surface-200/70 hover:text-foreground-400 transition">
        <span className="text-xs text-foreground-400 font-light">
          Connect your tools to GAIA
        </span>
        <div className="ml-3 flex items-center gap-1">
          {shuffledIntegrations.slice(0, 10).map((integration) => (
            <div
              key={integration.id}
              className="opacity-60 transition duration-200 hover:scale-150 hover:rotate-6 hover:opacity-120"
              title={integration.name}
            >
              {getToolCategoryIcon(integration.id, {
                size: 14,
                width: 14,
                height: 14,
                showBackground: false,
                className: "h-[14px] w-[14px] object-contain",
              })}
            </div>
          ))}
          <div>
            {shuffledIntegrations.length > 10 && (
              <div className="text-xs ml-1 font-light">
                +{shuffledIntegrations.length - 10}
              </div>
            )}
          </div>
          <ChevronRight width={18} height={18} className="ml-3" />
        </div>
      </div>
    </Button>
  );
};

export default IntegrationsBanner;
