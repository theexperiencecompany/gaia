import type { Postmark } from "@shared/api/generated";

import type { FoldedBriefSummary } from "../components/BriefCard";

/** The brief a stamp came on, folded: its edition rides along so it can be readied before it is pressed. */
export function postmarkBrief(postmark: Postmark): FoldedBriefSummary {
  return {
    headline: `Your brief from ${postmark.city}`,
    imageUrl: postmark.edition_image_url,
    editionFold: postmark.edition_fold,
    editionPaper: postmark.edition_paper,
  };
}
