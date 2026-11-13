import type { NotificationPlatform } from "@/features/notification/constants";
import { api } from "@/lib/api/typed";

export const chatChannelApi = {
  // The order GAIA picks the one platform it texts on.
  fetchPriority: () =>
    api.get("/api/v1/user/chat-channel-priority", { silent: true }),

  // Echoes back what was stored: duplicates are collapsed server-side.
  updatePriority: (priority: NotificationPlatform[]) =>
    api.patch("/api/v1/user/chat-channel-priority", {
      body: { priority },
      silent: true,
    }),
};
