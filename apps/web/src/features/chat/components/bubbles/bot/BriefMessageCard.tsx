"use client";

import { BriefingFold } from "@/features/briefing";
import type { BriefMessageData } from "@/types/features/briefingTypes";

/** GAIA's brief message: the folded letter card itself, which unfolds the edition when pressed. */
export function BriefMessageCard({ data }: { data: BriefMessageData }) {
  return (
    <div className="w-full max-w-56">
      <BriefingFold
        briefingId={data.briefing_id}
        brief={{
          headline: data.headline,
          date: data.date,
          kind: data.kind,
          imageUrl: data.edition_image_url,
          editionName: data.edition_name,
          stampCityName: data.stamp_city_name,
          needsYouCount: data.needs_you_count,
        }}
      />
    </div>
  );
}
