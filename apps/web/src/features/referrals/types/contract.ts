/**
 * The /api/v1/referrals contract as the core PR defines it, under the models'
 * own names, until `mise api:types` emits them into @shared/api/generated.
 * Once it does, api-schema-types flags every name here and this file becomes
 * one `export type { ... } from "@shared/api/generated"` line.
 */

export type ReferralCopyVariant = "gift" | "earn" | "time_back" | "insider";
export type ReferralLayoutVariant = "ticket" | "progress" | "minimal";
export type ReferredFriendStatus = "joined" | "paid";
export type ReferralInviteSurface =
  | "page"
  | "hover_card"
  | "agent"
  | "suggestion";
export type ReferralInviteStatus =
  | "sent"
  | "already_invited"
  | "invalid"
  | "unsubscribed"
  | "own_address";
export type ReferralSuggestionReason = "met" | "emailed";

export interface ReferralOffer {
  currency: string;
  monthly_regular_minor: number;
  monthly_intro_minor: number;
  intro_cycles: number;
  yearly_regular_minor: number;
  yearly_discount_minor: number;
}

export interface ReferredFriend {
  first_name: string;
  status: ReferredFriendStatus;
  joined_at: string;
  paid_at: string | null;
}

export interface ReferralMeResponse {
  code: string;
  share_link: string;
  offer: ReferralOffer;
  months_earned: number;
  months_applied: number;
  months_banked: number;
  next_billing_date: string | null;
  friends: ReferredFriend[];
  copy_variant: ReferralCopyVariant;
  layout_variant: ReferralLayoutVariant;
}

export interface ReferralResolveResponse {
  valid: boolean;
  referrer_first_name: string | null;
  referrer_picture: string | null;
  offer: ReferralOffer;
}

export interface ReferralSuggestion {
  name: string | null;
  email: string;
  reason: ReferralSuggestionReason;
  count: number;
}

export interface ReferralInviteResult {
  email: string;
  status: ReferralInviteStatus;
}
