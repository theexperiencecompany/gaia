"use client";

import { BriefingFold } from "@/features/briefing";
import type { BriefMessageData } from "@/types/features/briefingTypes";

/** The edition attached to GAIA's brief message: a folded letter that unfolds when pressed. */
export function BriefMessageCard({ data }: { data: BriefMessageData }) {
  return (
    <BriefingFold
      variant="letter"
      briefingId={data.briefing_id}
      brief={{
        headline: data.headline,
        imageUrl: data.edition_image_url,
        editionFold: data.edition_fold,
        editionPaper: data.edition_paper,
      }}
    />
  );
}
