"use client";

import { useQuery } from "@tanstack/react-query";
import { providersApi } from "@/features/settings/api/providersApi";

const SETUP_STATUS_QUERY_KEY = ["setup-status"];

export function useSetupStatus() {
  return useQuery({
    queryKey: SETUP_STATUS_QUERY_KEY,
    queryFn: () => providersApi.fetchSetupStatus(),
    staleTime: 60 * 1000,
  });
}
