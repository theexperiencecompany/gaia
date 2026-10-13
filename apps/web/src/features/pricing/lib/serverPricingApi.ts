import { serverApi, serverApiError } from "@/lib/api/server";

import type { Plan } from "../api/pricingApi";

const PLANS_TIMEOUT_MS = 10_000;

export async function getPlansServer(activeOnly = true): Promise<Plan[]> {
  const client = serverApi();
  if (!client) return [];

  const { data, error, response } = await client.GET("/api/v1/payments/plans", {
    params: { query: { active_only: activeOnly } },
    signal: AbortSignal.timeout(PLANS_TIMEOUT_MS),
  });
  if (error !== undefined || data === undefined) {
    const failure = serverApiError(response, error);
    throw new Error(`Failed to fetch plans from backend: ${failure.message}`, {
      cause: failure,
    });
  }
  return data;
}
