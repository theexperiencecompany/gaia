"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useUser } from "@/features/auth/hooks/useUser";
import { toast } from "@/lib/toast";

import { referralApi } from "../api/referralApi";
import {
  REFERRAL_OVERVIEW_STALE_TIME,
  REFERRAL_QUERY_KEYS,
} from "../constants";
import type { ResolveCodeResult } from "../types";

// Get the current user's referral overview (only when authenticated)
export const useReferralOverview = () => {
  const user = useUser();

  return useQuery({
    queryKey: REFERRAL_QUERY_KEYS.overview,
    queryFn: () => referralApi.getOverview(),
    staleTime: REFERRAL_OVERVIEW_STALE_TIME,
    enabled: !!user,
  });
};

/**
 * Resolve a referral code for the public invite landing page. Uses a plain
 * fetch (not React Query) so it works outside the app's QueryClientProvider, and
 * resolving arms attribution (the endpoint sets the gaia_ref cookie). Any
 * failure resolves to null so the page falls back to its generic hero.
 */
export const useResolveReferralCode = (code: string) => {
  const [data, setData] = useState<ResolveCodeResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!code) {
      setIsLoading(false);
      return;
    }
    let active = true;
    setIsLoading(true);
    referralApi
      .resolveCode(code)
      .then((result) => active && setData(result))
      .catch(() => active && setData(null))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
  }, [code]);

  return { data, isLoading };
};

// Invite friends by email
export const useInviteFriends = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (emails: string[]) => referralApi.invite(emails),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: REFERRAL_QUERY_KEYS.overview,
      });
      toast.success("Invites sent!");
    },
    onError: () => {
      toast.error("Failed to send invites");
    },
  });
};

/**
 * Lazily fetch Google contact suggestions for the invite field. Disabled on
 * mount (the endpoint hits Gmail/Composio); call `fetchContacts` when the user
 * clicks "Import from Google". The backend never errors — it returns [] when
 * Gmail isn't connected — so a successful, empty result is a valid state.
 */
export const useInviteContacts = () => {
  const query = useQuery({
    queryKey: REFERRAL_QUERY_KEYS.contacts,
    queryFn: () => referralApi.getInviteContacts(),
    enabled: false,
    gcTime: 0,
  });

  return {
    contacts: query.data ?? [],
    isLoading: query.isFetching,
    hasFetched: query.isFetched,
    fetchContacts: query.refetch,
  };
};

// Update the user's referral code
export const useUpdateReferralCode = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (code: string) => referralApi.updateCode(code),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: REFERRAL_QUERY_KEYS.overview,
      });
      toast.success("Referral code updated!");
    },
    onError: () => {
      toast.error("Failed to update referral code");
    },
  });
};
