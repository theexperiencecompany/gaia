import type { NotificationPlatform } from "@/features/notification/constants";
import { apiService } from "@/lib/api/service";
import type { Briefing } from "@/types/features/briefingTypes";

export interface BriefingPreferences {
  chat_channel_priority: NotificationPlatform[];
}

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

  // The ordered chat-channel priority: the brief lands on the first connected,
  // enabled platform in this order.
  fetchChannelPriority: async (): Promise<BriefingPreferences> => {
    return apiService.get<BriefingPreferences>("/briefings/preferences", {
      silent: true,
    });
  },

  updateChannelPriority: async (
    order: NotificationPlatform[],
  ): Promise<BriefingPreferences> => {
    return apiService.patch<BriefingPreferences>(
      "/briefings/preferences",
      { chat_channel_priority: order },
      { silent: true },
    );
  },
};
