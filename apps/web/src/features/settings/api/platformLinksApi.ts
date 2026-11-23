import { queryOptions } from "@tanstack/react-query";

import type { BotPlatform } from "@/config/botPlatforms";
import { api } from "@/lib/api/typed";

import { preferenceKeys } from "./queryKeys";

/** The chat apps linked to the user's account, and linking or unlinking one. */
export const platformLinksApi = {
  fetch: () => api.get("/api/v1/platform-links", { silent: true }),

  // An OAuth URL, a number to text, or manual instructions, depending on the platform.
  connect: (platform: BotPlatform, phone?: string) =>
    api.post("/api/v1/platform-links/{platform}/connect", {
      path: { platform },
      body: phone ? { phone } : {},
      silent: true,
    }),

  disconnect: (platform: BotPlatform) =>
    api.delete("/api/v1/platform-links/{platform}", {
      path: { platform },
      silent: true,
    }),
};

export const platformLinksQuery = () =>
  queryOptions({
    queryKey: preferenceKeys.platformLinks,
    queryFn: platformLinksApi.fetch,
  });
