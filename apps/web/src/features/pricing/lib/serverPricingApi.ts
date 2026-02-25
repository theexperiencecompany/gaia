import axios from "axios";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

import type { Plan } from "../api/pricingApi";

export async function getPlansServer(activeOnly = true): Promise<Plan[]> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  try {
    const apiBaseUrl = getServerApiBaseUrl();
    if (!apiBaseUrl) return [];

    const response = await axios.get<Plan[]>(`${apiBaseUrl}/payments/plans`, {
      headers,
      params: { active_only: activeOnly },
      timeout: 10000, // 10 second timeout
    });

    if (!Array.isArray(response.data)) {
      console.warn(
        "Failed to fetch plans server-side: backend returned non-array payload",
      );
      return [];
    }

    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || error.message;
      throw new Error(`Failed to fetch plans from backend: ${message}`);
    }
    throw error;
  }
}
