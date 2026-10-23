/** GAIA's brief message tool data (briefing_data), as the API's BriefingCardData writes it. */
export interface BriefMessageData {
  briefing_id: string;
  date: string;
  kind: "daily" | "weekly";
  headline: string;
  edition_image_url: string | null;
  edition_fold: number | null;
  edition_name: string | null;
  stamp_city_name: string | null;
  needs_you_count: number;
}
