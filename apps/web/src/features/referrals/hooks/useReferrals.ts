"use client";

import { ApiError } from "@shared/api";
import type { ReferralMeResponse } from "@shared/api/generated";
import { useQuery } from "@tanstack/react-query";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { referralsApi } from "../api/referralsApi";
import type { InviteSender } from "../stores/inviteStore";

/** The API's code for a caller with no active subscription. */
const SUBSCRIPTION_REQUIRED = "REFERRAL_SUBSCRIPTION_REQUIRED";
const ME_STALE_MS = 60 * 1000;

export type ReferralMeState =
  | { status: "loading" }
  | { status: "ready"; me: ReferralMeResponse }
  | { status: "subscribe_first" }
  | { status: "error"; retry: () => void };

/** The caller's referral overview; only Pro users have one, so it waits until the plan is known. */
export function useReferralMe(): ReferralMeState {
  const { isPaid, isUnknown } = useIsPaid();
  const query = useQuery({
    queryKey: ["referrals", "me"],
    queryFn: referralsApi.getMe,
    enabled: !isUnknown && isPaid,
    staleTime: ME_STALE_MS,
    retry: (failures, error) =>
      !(error instanceof ApiError && error.status < 500) && failures < 2,
  });

  if (isUnknown) return { status: "loading" };
  if (!isPaid) return { status: "subscribe_first" };
  if (query.data) return { status: "ready", me: query.data };
  if (
    query.error instanceof ApiError &&
    query.error.code === SUBSCRIPTION_REQUIRED
  ) {
    return { status: "subscribe_first" };
  }
  if (query.isError)
    return { status: "error", retry: () => void query.refetch() };
  return { status: "loading" };
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

/** The hover card's invite sender: only Pro users can invite, and never to their own address. */
export function useHoverCardInvite(email: string): InviteSender | undefined {
  const { isPaid } = useIsPaid();
  const user = useCurrentUser();
  const isOwnAddress =
    !!user.email && user.email.toLowerCase() === email.toLowerCase();
  return isPaid && !isOwnAddress ? sendReferralInvite : undefined;
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
