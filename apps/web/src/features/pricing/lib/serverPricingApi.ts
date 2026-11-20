import { serverApi, serverApiError } from "@/lib/api/server";

import type { Plan } from "../api/pricingApi";

/** How long the plan list serves from the data cache, the pricing page's old ISR window. */
const PLANS_REVALIDATE_S = 86_400;

export async function getPlansServer(activeOnly = true): Promise<Plan[]> {
  const client = serverApi({ revalidate: PLANS_REVALIDATE_S });
  if (!client) return [];

  const { data, error, response } = await client.GET("/api/v1/payments/plans", {
    params: { query: { active_only: activeOnly } },
  });
  if (error !== undefined || data === undefined) {
    const failure = serverApiError(response, error);
    throw new Error(`Failed to fetch plans from backend: ${failure.message}`, {
      cause: failure,
    });
  }
  return data;
}
