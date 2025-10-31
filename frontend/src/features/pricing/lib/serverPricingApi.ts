import axios from "axios";

import type { Plan } from "../api/pricingApi";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export async function getPlansServer(activeOnly = true): Promise<Plan[]> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  try {
    const response = await axios.get<Plan[]>(`${API_BASE_URL}/payments/plans`, {
      headers,
      params: { active_only: activeOnly },
      timeout: 10000, // 10 second timeout
    });

    if (!Array.isArray(response.data)) {
      throw new Error("Invalid response format from backend");
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
