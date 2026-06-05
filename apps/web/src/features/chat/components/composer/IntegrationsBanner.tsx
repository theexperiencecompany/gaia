import { shuffle } from "lodash";
import type React from "react";
import { useMemo } from "react";

import { ChevronRight } from "@/components/shared/icons";
import { useFittingIconCount } from "@/features/chat/hooks/useFittingIconCount";
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

  const { containerRef, visibleCount } = useFittingIconCount(
    shuffledIntegrations.length,
  );
  const overflowCount = shuffledIntegrations.length - visibleCount;

  if (isLoading || integrations.length === 0 || hasMessages) {
    return null;
  }

  return (
    // No z-index here — z-auto means DOM order, so indicators rendered after paint on top.
    // pointer-events-none so the pb-10 overlap doesn't block the searchbar below.
    <div className="absolute -top-9 flex w-full justify-center pointer-events-none pb-10">
      <button
        type="button"
        className="flex w-[90%] items-center gap-3 rounded-full bg-zinc-800/40 pr-8 pl-8 pt-2 text-xs text-foreground-300 hover:bg-zinc-800/70 hover:text-zinc-400 transition pointer-events-auto cursor-pointer pb-14!"
        onClick={onToggleSlashCommand}
      >
        <span className="text-xs whitespace-nowrap shrink-0">
          Connect your tools to GAIA
        </span>
        <div
          ref={containerRef}
          className="flex min-w-0 flex-1 items-center justify-end gap-1 overflow-hidden"
        >
          {shuffledIntegrations.slice(0, visibleCount).map((integration) => (
            <div
              key={integration.id}
              className="shrink-0 opacity-60 transition duration-200 hover:scale-150 hover:rotate-6 hover:opacity-100"
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
          {overflowCount > 0 && visibleCount > 0 && (
            <div className="text-xs ml-1 shrink-0">+{overflowCount}</div>
          )}
        </div>
        <ChevronRight width={18} height={18} className="shrink-0" />
      </button>
    </div>
  );
};

export default IntegrationsBanner;
