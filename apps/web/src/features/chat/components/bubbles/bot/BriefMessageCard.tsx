"use client";

import {
  type BriefCard,
  BriefingFold,
  BriefLetter,
  foldedBrief,
} from "@/features/briefing";

/** The edition attached to GAIA's brief message: a folded letter that unfolds when pressed. */
export function BriefMessageCard({ data }: { data: BriefCard }) {
  const brief = foldedBrief(data);
  return (
    <BriefingFold briefingId={data.briefing_id} brief={brief}>
      {(trigger) => <BriefLetter brief={brief} trigger={trigger} />}
    </BriefingFold>
  );
}
