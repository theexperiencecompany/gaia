/**
 * Composer integrations banner.
 *
 * Rendered inside Composer's `.searchbar`, which is `position: relative;
 * z-index: 2` and therefore a stacking context. The arch is a separate,
 * aria-hidden, pointer-events-none layer at the old button's 82px height; it
 * uses `-z-10` so the textarea and form paint above it and the placeholder
 * never dims where they overlap. Only the 34px pill is interactive, and the
 * wrapper stays pointer-events-none so the arch's lower 46px cannot intercept
 * clicks. The composer shell also focuses the textarea on non-control clicks
 * (Composer.tsx), covering the arch and padding area.
 *
 * Do not put a background back on the button or add z-index to the wrapper:
 * either one paints the translucent surface over the textarea again.
 */

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
    // No z-index here — z-auto means DOM order, so indicators rendered after paint on top.
    // pointer-events-none so only the pill itself catches clicks, never the composer below.
    <div className="pointer-events-none absolute -top-9 flex w-full justify-center">
      <div className="group relative w-[90%]">
        {/* The 82px arch continues down behind the composer. It is visual only,
            so the composer keeps every click the old padded button stole. */}
        <div
          aria-hidden="true"
          className="absolute inset-x-0 top-0 -z-10 h-[82px] rounded-full bg-zinc-800/40 transition-colors duration-200 group-hover:bg-zinc-800/70"
        />
        <button
          type="button"
          className="relative flex w-full items-center gap-3 rounded-full px-8 py-2 text-xs text-zinc-600 transition-colors hover:text-zinc-400 pointer-events-auto cursor-pointer"
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
    </div>
  );
};

export default IntegrationsBanner;
