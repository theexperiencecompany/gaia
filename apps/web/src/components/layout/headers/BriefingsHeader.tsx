"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { EarthIcon, News01Icon, Settings01Icon } from "@icons";
import Link from "next/link";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
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
        <Button
          as={Link}
          href={POSTMARKS_SETTINGS_PATH}
          size="sm"
          variant="light"
          className="text-zinc-400 data-[hover=true]:text-zinc-100"
          startContent={<EarthIcon className="size-4" />}
        >
          Postmarks
        </Button>
        <Tooltip content="Briefing settings" closeDelay={0}>
          <Button
            as={Link}
            href={BRIEFINGS_SETTINGS_PATH}
            size="sm"
            variant="light"
            isIconOnly
            aria-label="Briefing settings"
            className="text-zinc-400 data-[hover=true]:text-zinc-100"
          >
            <Settings01Icon className="size-4" />
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}
