"use client";

import type { ReferralCopyVariant } from "@shared/api/generated";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { randomUnit } from "@/lib/random";
import { referralsApi } from "../api/referralsApi";
import { LIVE_LANDING_VARIANTS } from "../referralCopy";

const LANDING_VARIANT_KEY = "gaia_invite_landing_variant";

/** One landing angle per browser, so a reload or a second invite reads the same as the first. */
function pickLandingVariant(): ReferralCopyVariant {
  const stored = localStorage.getItem(LANDING_VARIANT_KEY);
  const known = LIVE_LANDING_VARIANTS.find((variant) => variant === stored);
  if (known) return known;
  const picked =
    LIVE_LANDING_VARIANTS[
      Math.floor(randomUnit() * LIVE_LANDING_VARIANTS.length)
    ];
  localStorage.setItem(LANDING_VARIANT_KEY, picked);
  return picked;
}

/** Resolve the code from the browser, so the API's first-touch cookie lands on this visitor. */
export function useInviteLanding(code: string) {
  const [variant, setVariant] = useState<ReferralCopyVariant | null>(null);
  // localStorage exists only after mount; the server pass renders the loading state.
  useEffect(() => setVariant(pickLandingVariant()), []);
  const query = useQuery({
    queryKey: ["referrals", "resolve", code, variant],
    queryFn: () =>
      referralsApi.resolve(code, variant ?? LIVE_LANDING_VARIANTS[0]),
    enabled: variant !== null,
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  });
  return { variant, invite: query.data, isError: query.isError };
}
