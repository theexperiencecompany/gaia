import type { NotificationPlatform } from "@/features/notification/constants";
import { apiService } from "@/lib/api/service";

export interface ChannelPriority {
  priority: NotificationPlatform[];
}

export const chatChannelApi = {
  // The order GAIA picks the one platform it texts on.
  fetchPriority: (): Promise<ChannelPriority> =>
    apiService.get<ChannelPriority>("/user/chat-channel-priority", {
      silent: true,
    }),

  // Echoes back what was stored: duplicates are collapsed server-side.
  updatePriority: (
    priority: NotificationPlatform[],
  ): Promise<ChannelPriority> =>
    apiService.patch<ChannelPriority>(
      "/user/chat-channel-priority",
      { priority },
      { silent: true },
    ),
};
