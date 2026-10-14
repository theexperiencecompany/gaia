"use client";

import type { BriefingModel } from "@shared/api/generated";

import { StandalonePage } from "@/components/layout/StandalonePage";

import {
  BriefingEdition,
  type BriefingEditionPayload,
} from "./BriefingEdition";

export interface StandaloneBriefingProps {
  briefing: Pick<BriefingModel, "edition_image_url"> & {
    payload: BriefingEditionPayload;
  };
}

/**
 * A brief on its own full page, outside the app shell: opened from the email image,
 * the chat link or the Briefings list.
 */
export function StandaloneBriefing({ briefing }: StandaloneBriefingProps) {
  return (
    <StandalonePage>
      <BriefingEdition
        payload={briefing.payload}
        imageUrl={briefing.edition_image_url}
      />
    </StandalonePage>
  );
}
