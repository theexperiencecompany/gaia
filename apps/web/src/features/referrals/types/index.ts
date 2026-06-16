export type ReferralStatus =
  | "invited"
  | "signed_up"
  | "activated"
  | "upgraded"
  | "renewed"
  | "reverted";

export type ReferralChannel = "link" | "email" | "google_import" | "social";

export interface MilestoneState {
  threshold: number;
  reward_months: number;
  cumulative_months: number;
  status: "done" | "next" | "locked";
}

export interface FriendReferral {
  display: string;
  status: ReferralStatus;
  channel: ReferralChannel;
  created_at: string;
  upgraded_at: string | null;
}

export interface EarnedReward {
  months_granted: number;
  milestone_threshold: number;
  discount_code: string | null;
  status: "granted" | "reverted";
  granted_at: string;
}

export interface ReferralStats {
  invited: number;
  joined: number;
  upgraded: number;
  months_earned: number;
}

export interface ReferralOverview {
  code: string;
  share_link: string;
  points: number;
  points_into_current_goal: number;
  next_goal_threshold: number;
  next_goal_reward_months: number;
  progress_pct: number;
  ladder: MilestoneState[];
  stats: ReferralStats;
  friends: FriendReferral[];
  rewards: EarnedReward[];
}

export interface ResolveCodeResult {
  valid: boolean;
  referrer_name: string | null;
  referrer_picture: string | null;
  offer_label: string;
}

export interface InviteResult {
  sent: string[];
  skipped: string[];
}

export interface InviteContact {
  name: string | null;
  email: string;
}

export interface UpdateCodeResult {
  code: string;
  share_link: string;
}
