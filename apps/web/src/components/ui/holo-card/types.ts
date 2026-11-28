import type { PersonalizationResponse } from "@shared/api/generated";

/** The card's API fields; the public card carries no id and may omit its overlay. */
export type HoloCardDisplayData = Pick<
  PersonalizationResponse,
  | "house"
  | "name"
  | "personality_phrase"
  | "user_bio"
  | "account_number"
  | "member_since"
> &
  Partial<
    Pick<
      PersonalizationResponse,
      "overlay_color" | "overlay_opacity" | "holo_card_id"
    >
  >;

export interface HoloCardProps {
  data: HoloCardDisplayData;
  height?: number;
  width?: number;
  showSparkles?: boolean;
  className?: string;
  children?: React.ReactNode;
}
