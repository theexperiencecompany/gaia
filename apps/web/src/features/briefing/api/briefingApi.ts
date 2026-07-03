import { apiService } from "@/lib/api/service";
import type { Briefing } from "@/types/features/briefingTypes";

export const briefingApi = {
  // Fetch the most recent briefing. 404 means the user has none yet — that's
  // an expected state, not an error, so it resolves to null instead of throwing.
  fetchLatestBriefing: async (): Promise<Briefing | null> => {
    try {
      return await apiService.get<Briefing>("/briefings/latest", {
        silent: true,
      });
    } catch (error: unknown) {
      const status = (error as { response?: { status?: number } }).response
        ?.status;
      if (status === 404) {
        return null;
      }
      throw error;
    }
  },

  // Fetch past briefings, most recent first.
  fetchBriefings: async (limit = 30): Promise<Briefing[]> => {
    const response = await apiService.get<{ briefings: Briefing[] }>(
      `/briefings?limit=${limit}`,
      { silent: true },
    );
    return response.briefings;
  },
};
