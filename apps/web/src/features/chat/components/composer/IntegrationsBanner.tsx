import shuffle from "lodash/shuffle";
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
    // Normal-flow sibling directly above the composer box — NOT absolutely
    // positioned against it. Absolute positioning anchored a fixed -top-9 to
    // the composer box alone, so its reach upward never adapted to whatever
    // rendered above it (e.g. PaywallNotice growing to two lines at a narrow
    // width): the pill's fixed reach then intruded into the notice's own
    // rendered text instead of just the empty margin above it. Sitting in
    // flow means the pill always starts right after its actual previous
    // sibling, at any height. The composer box (`.searchbar`, z-2) still
    // paints over the small `-mb-8` tuck below, which is the only
    // intentional overlap — with the composer itself, not with a sibling.
    // `searchbar` (globals.css) is the width rule the composer box itself uses
    // — 50% desktop / 95% phone. Wearing it here keeps the pill locked to the
    // composer's width at every breakpoint instead of spanning the full
    // container, which is what `w-full` did once this moved out of the box.
    <div className="searchbar relative z-0 flex justify-center pointer-events-none pt-2 pb-6 -mb-8">
      <button
        type="button"
        className="flex w-[90%] items-center gap-3 rounded-full bg-zinc-800/40 px-8 py-2 text-xs text-foreground-300 hover:bg-zinc-800/70 hover:text-zinc-400 transition pointer-events-auto cursor-pointer"
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
