"use client";

import { ApiError } from "@shared/api";
import type { ReferralMeResponse } from "@shared/api/generated";
import { useQuery } from "@tanstack/react-query";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";
import { referralsApi } from "../api/referralsApi";
import type { InviteSender } from "../stores/inviteStore";

const ME_STALE_MS = 60 * 1000;

export type ReferralMeState =
  | { status: "loading" }
  | { status: "ready"; me: ReferralMeResponse }
  | { status: "subscribe_first" }
  | { status: "disabled" }
  | { status: "error"; retry: () => void };

/** The caller's referral overview; the server decides whether the program is on and whether they may refer. */
export function useReferralMe(): ReferralMeState {
  const query = useQuery({
    queryKey: ["referrals", "me"],
    queryFn: referralsApi.getMe,
    staleTime: ME_STALE_MS,
    retry: (failures, error) =>
      !(error instanceof ApiError && error.status < 500) && failures < 2,
  });

  if (query.data) return { status: "ready", me: query.data };
  if (query.error instanceof ApiError) {
    if (query.error.code === API_ERROR_CODES.REFERRALS_DISABLED) {
      return { status: "disabled" };
    }
    if (query.error.code === API_ERROR_CODES.REFERRAL_SUBSCRIPTION_REQUIRED) {
      return { status: "subscribe_first" };
    }
  }
  if (query.isError)
    return { status: "error", retry: () => void query.refetch() };
  return { status: "loading" };
}

/** The gift the caller's checkout applies, from the friend who referred them; null when none is owed. */
export function useFriendGift() {
  return useQuery({
    queryKey: ["referrals", "gift"],
    queryFn: referralsApi.getGift,
    staleTime: Number.POSITIVE_INFINITY,
    select: (data) => data.gift,
  });
}

/** Ranked people to invite; empty when neither Gmail nor Calendar is connected. */
export function useReferralSuggestions(enabled: boolean) {
  return useQuery({
    queryKey: ["referrals", "suggestions"],
    queryFn: referralsApi.getSuggestions,
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    select: (data) => data.suggestions,
  });
}

/** The hover card's invite sender: only users with a live invite link can invite, never to their own address. */
export function useHoverCardInvite(email: string): InviteSender | undefined {
  const canRefer = useReferralMe().status === "ready";
  const user = useCurrentUser();
  const isOwnAddress =
    !!user.email && user.email.toLowerCase() === email.toLowerCase();
  return canRefer && !isOwnAddress ? sendReferralInvite : undefined;
}

/** One address through POST /invites; the server's per-address verdict is the button's final label. */
export const sendReferralInvite: InviteSender = async (email, surface) => {
  const { results } = await referralsApi.sendInvites([email], surface);
  const result = results.find(
    (r) => r.email.toLowerCase() === email.toLowerCase(),
  );
  if (!result) throw new Error(`No invite result returned for ${email}`);
  return result.status;
};
