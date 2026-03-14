import { shuffle } from "lodash";
import type React from "react";
import { useMemo } from "react";

import { ChevronRight } from "@/components/shared/icons";
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
  const shuffledIntegrations = useMemo(
    () => shuffle(integrations),
    [integrations],
  );

  if (isLoading || integrations.length === 0 || hasMessages) {
    return null;
  }

  return (
    // No z-index here — z-auto means DOM order, so indicators rendered after paint on top.
    // pointer-events-none so the pb-10 overlap doesn't block the searchbar below.
    <div className="absolute -top-9 flex w-full justify-center pointer-events-none pb-10">
      <button
        type="button"
        className="flex w-[90%] items-center justify-between rounded-full bg-zinc-800/40 pr-4 pl-6 py-2 text-xs text-foreground-300 hover:bg-zinc-800/70 hover:text-zinc-400 transition pointer-events-auto cursor-pointer"
        onClick={onToggleSlashCommand}
      >
        <span className="text-xs">Connect your tools to GAIA</span>
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
          {shuffledIntegrations.length > 10 && (
            <div className="text-xs ml-1">
              +{shuffledIntegrations.length - 10}
            </div>
          )}
          <ChevronRight width={18} height={18} className="ml-3" />
        </div>
      </button>
    </div>
  );
};

export default IntegrationsBanner;
