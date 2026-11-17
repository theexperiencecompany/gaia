"use client";

import { Tooltip } from "@heroui/react";
import { EarthIcon, News01Icon, Settings01Icon } from "@icons";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { LinkButton } from "@/components/shared/LinkButton";
import {
  BRIEFINGS_SETTINGS_PATH,
  POSTMARKS_SETTINGS_PATH,
} from "@/features/briefing/constants";

/** The Briefings page's title, with its two neighbours: the stamps briefs bring, and when briefs come. */
export default function BriefingsHeader() {
  return (
    <div className="flex w-full items-center justify-between">
      <HeaderTitle
        icon={<News01Icon width={20} height={20} />}
        text="Briefings"
      />
      <div className="flex items-center gap-1">
        <LinkButton
          href={POSTMARKS_SETTINGS_PATH}
          size="sm"
          variant="ghost"
          tone="muted"
          hoverTone="strong"
        >
          <EarthIcon className="size-4" />
          Postmarks
        </LinkButton>
        <Tooltip closeDelay={0}>
          <LinkButton
            href={BRIEFINGS_SETTINGS_PATH}
            size="sm"
            variant="ghost"
            isIconOnly
            aria-label="Briefing settings"
            tone="muted"
            hoverTone="strong"
          >
            <Settings01Icon className="size-4" />
          </LinkButton>
          <Tooltip.Content>Briefing settings</Tooltip.Content>
        </Tooltip>
      </div>
    </div>
  );
}
