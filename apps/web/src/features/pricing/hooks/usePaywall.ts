"use client";

import {
  type QueryState,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { type PaywallResponse, pricingApi } from "../api/pricingApi";
import { PAYWALL_JOBS_MAX_READS, PAYWALL_JOBS_POLL_MS } from "../constants";

const PAYWALL_QUERY_KEY = ["paywall"] as const;

/** Whether the drafted jobs could still land: the preview is on, none have yet, and reads remain. */
const jobsStillDrafting = (
  state: QueryState<PaywallResponse> | undefined,
): boolean =>
  state?.data?.variant === "value_preview" &&
  state.data.starting_jobs.length === 0 &&
  state.dataUpdateCount < PAYWALL_JOBS_MAX_READS;

/**
 * The onboarding paywall's variant and the jobs its preview lists. Re-read
 * while the background draft from the Q2 save is still being written, for a
 * bounded number of reads; past that the preview stands on the answers alone.
 */
export function usePaywall() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: PAYWALL_QUERY_KEY,
    queryFn: () => pricingApi.getPaywall(),
    staleTime: Number.POSITIVE_INFINITY,
    refetchInterval: (current) =>
      jobsStillDrafting(current.state) ? PAYWALL_JOBS_POLL_MS : false,
  });
  return {
    paywall: query.data,
    isError: query.isError,
    // Re-evaluated on every read: each one moves dataUpdatedAt, which re-renders.
    jobsStillDrafting:
      query.dataUpdatedAt > 0 &&
      jobsStillDrafting(queryClient.getQueryState(PAYWALL_QUERY_KEY)),
  };
}
