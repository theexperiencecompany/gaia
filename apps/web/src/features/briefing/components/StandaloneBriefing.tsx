"use client";

import type { BriefingView } from "@shared/api/generated";

import { StandalonePage } from "@/components/layout/StandalonePage";
import { ShareLinkControls } from "@/features/short-links/components/ShareLinkControls";

import { BACK_TO_BRIEFINGS } from "../constants";

import { BriefingEdition } from "./BriefingEdition";

export interface StandaloneBriefingProps {
  briefing: BriefingView;
  /** Set on the owner's own page, which can share the brief or stop sharing it. */
  ownedBriefingId?: string;
}

/**
 * A brief on its own full page, outside the app shell: opened from the email image,
 * the chat link or the Briefings list.
 */
export function StandaloneBriefing({
  briefing,
  ownedBriefingId,
}: StandaloneBriefingProps) {
  return (
    <StandalonePage
      width="letter"
      back={BACK_TO_BRIEFINGS}
      actions={
        ownedBriefingId && (
          <ShareLinkControls
            target={{ type: "briefing", id: ownedBriefingId }}
          />
        )
      }
    >
      <BriefingEdition
        payload={briefing.payload}
        imageUrl={briefing.card.edition?.image_url}
        leftOut={briefing.left_out}
      />
    </StandalonePage>
  );
}
