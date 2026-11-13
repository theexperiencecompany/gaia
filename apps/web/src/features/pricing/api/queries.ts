import { queryOptions } from "@tanstack/react-query";
import type { RequestOrigin } from "@/lib/api/typed";

import { pricingApi } from "./pricingApi";

/** The `["subscription-status"]` query every paid-only gate reads; a poll re-reads it as background. */
export const subscriptionStatusQuery = (origin?: RequestOrigin) =>
  queryOptions({
    queryKey: ["subscription-status"],
    queryFn: () => pricingApi.getSubscriptionStatus(origin),
    staleTime: 60 * 1000,
    // An auth failure is not transient.
    retry: false,
  });
