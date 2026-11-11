"use client";

import type { ReferralCopyVariant } from "@shared/api/generated";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { currentUserQueryOptions } from "@/features/auth/hooks/useCurrentUser";
import { referralsApi } from "../api/referralsApi";
import { LIVE_LANDING_VARIANTS } from "../referralCopy";

const LANDING_VARIANT_KEY = "gaia_invite_landing_variant";

/** One landing angle per browser, so a reload or a second invite reads the same as the first. */
function pickLandingVariant(): ReferralCopyVariant {
  const stored = localStorage.getItem(LANDING_VARIANT_KEY);
  const known = LIVE_LANDING_VARIANTS.find((variant) => variant === stored);
  if (known) return known;
  const [draw] = crypto.getRandomValues(new Uint32Array(1));
  const picked = LIVE_LANDING_VARIANTS[draw % LIVE_LANDING_VARIANTS.length];
  localStorage.setItem(LANDING_VARIANT_KEY, picked);
  return picked;
}

/** Resolve the code from the browser, so the API's first-touch cookie lands on this visitor; never for a member. */
export function useInviteLanding(code: string) {
  const [variant, setVariant] = useState<ReferralCopyVariant | null>(null);
  // localStorage exists only after mount; the server pass renders the loading state.
  useEffect(() => setVariant(pickLandingVariant()), []);
  const { isAuthenticated } = useAuth();
  // Resolving sets the attribution cookie, so it waits for /user/me to refuse first.
  const { isError: isSignedOut } = useQuery(currentUserQueryOptions);
  const query = useQuery({
    queryKey: ["referrals", "resolve", code, variant],
    queryFn: () =>
      referralsApi.resolve(code, variant ?? LIVE_LANDING_VARIANTS[0]),
    enabled: variant !== null && isSignedOut && !isAuthenticated,
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  });
  return {
    variant,
    isSignedIn: isAuthenticated,
    invite: query.data,
    isError: query.isError,
  };
}
