export interface HoloCardDisplayData {
  house: string;
  name: string;
  personality_phrase: string;
  user_bio: string;
  account_number: number | string;
  member_since: string;
  overlay_color?: string;
  overlay_opacity?: number;
  holo_card_id?: string;
}

export interface HoloCardProps {
  data: HoloCardDisplayData;
  height?: number;
  width?: number;
  showSparkles?: boolean;
  className?: string;
  children?: React.ReactNode;
}
