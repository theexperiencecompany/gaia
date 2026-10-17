"use client";

import type { BriefingModel } from "@shared/api/generated";

import { StandalonePage } from "@/components/layout/StandalonePage";
import { ShareLinkControls } from "@/features/short-links/components/ShareLinkControls";

import {
  BriefingEdition,
  type BriefingEditionPayload,
} from "./BriefingEdition";

export interface StandaloneBriefingProps {
  briefing: Pick<BriefingModel, "edition_image_url"> & {
    payload: BriefingEditionPayload;
  };
  /** Set on the owner's own page, which can share the brief or stop sharing it. */
  ownedBriefingId?: string;
}

// The edition image is a permanent CDN URL already embedded in the brief's email,
// so stopping the link cannot take the picture back.
const BRIEF_STOP_WARNING =
  "The edition image keeps its own address, which may already be in your email, so it stays viewable.";

/**
 * A brief on its own full page, outside the app shell: opened from the email image,
 * the chat link or the Briefings list.
 */
export function StandaloneBriefing({
  briefing,
  ownedBriefingId,
}: StandaloneBriefingProps) {
  return (
    <StandalonePage>
      {ownedBriefingId && (
        <div className="flex justify-end">
          <ShareLinkControls
            targetType="briefing"
            targetId={ownedBriefingId}
            stopWarning={BRIEF_STOP_WARNING}
          />
        </div>
      )}
      <BriefingEdition
        payload={briefing.payload}
        imageUrl={briefing.edition_image_url}
      />
    </StandalonePage>
  );
}
