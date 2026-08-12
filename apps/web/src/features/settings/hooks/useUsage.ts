"use client";

import { useQuery } from "@tanstack/react-query";

import { usageApi } from "../api/usageApi";

export const useUsageSummary = () => {
  return useQuery({
    queryKey: ["usageSummary"],
    queryFn: () => usageApi.getUsageSummary(),
    staleTime: 60 * 1000, // 30 seconds - usage data should be fresh
    retry: 2,
    refetchOnWindowFocus: true, // Refetch when window gains focus
    refetchOnMount: true, // Refetch when component mounts (navigation)
  });
};

export const useUsageHistory = (days = 30) => {
  return useQuery({
    queryKey: ["usageHistory", days],
    queryFn: () => usageApi.getUsageHistory(days),
    staleTime: 5 * 60 * 1000, // history moves slowly; 5 min is plenty
    retry: 2,
  });
};

export const useUsageActivity = (days = 365) => {
  return useQuery({
    queryKey: ["usageActivity", days],
    queryFn: () => usageApi.getUsageActivity(days),
    staleTime: 10 * 60 * 1000, // the year grid changes at most once a day
    retry: 2,
  });
};
