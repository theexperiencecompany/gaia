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
