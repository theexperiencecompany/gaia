import type { ChannelPlatform } from "@gaia/shared/types";
import type { QuietHours } from "@shared/api/generated";
import { queryOptions } from "@tanstack/react-query";

import type { NotificationPlatform } from "@/features/notification/constants";
import { api } from "@/lib/api/typed";

import { preferenceKeys } from "./queryKeys";

/** Where and when GAIA may reach the user: channels, the chat app it texts first, quiet hours. */
export const preferencesApi = {
  fetchChannels: () =>
    api.get("/api/v1/notifications/preferences/channels", { silent: true }),

  // Echoes back every channel's stored state; silent so the switch rolls back and words its own toast.
  updateChannel: (channel: ChannelPlatform, enabled: boolean) =>
    api.put("/api/v1/notifications/preferences/channels", {
      body: { [channel]: enabled },
      silent: true,
    }),

  // The order GAIA picks the one platform it texts on.
  fetchChatChannelPriority: () =>
    api.get("/api/v1/user/chat-channel-priority", { silent: true }),

  // Echoes back what was stored: duplicates are collapsed server-side.
  updateChatChannelPriority: (priority: NotificationPlatform[]) =>
    api.patch("/api/v1/user/chat-channel-priority", {
      body: { priority },
      silent: true,
    }),

  fetchQuietHours: () => api.get("/api/v1/user/quiet-hours", { silent: true }),

  // Echoes back what was stored.
  updateQuietHours: (hours: QuietHours) =>
    api.patch("/api/v1/user/quiet-hours", {
      body: hours,
      errorMessage: "Couldn't save your quiet hours",
    }),
};

export const channelPreferencesQuery = () =>
  queryOptions({
    queryKey: preferenceKeys.channels,
    queryFn: preferencesApi.fetchChannels,
  });

export const chatChannelPriorityQuery = () =>
  queryOptions({
    queryKey: preferenceKeys.chatChannelPriority,
    queryFn: preferencesApi.fetchChatChannelPriority,
  });

export const quietHoursQuery = () =>
  queryOptions({
    queryKey: preferenceKeys.quietHours,
    queryFn: preferencesApi.fetchQuietHours,
  });
