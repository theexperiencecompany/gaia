import type { AttentionSettings } from "@shared/api/generated";
import { api } from "@/lib/api/typed";

export const attentionApi = {
  fetch: () => api.get("/api/v1/user/attention", { silent: true }),

  // Echoes back what was stored.
  update: (settings: AttentionSettings) =>
    api.put("/api/v1/user/attention", {
      body: settings,
      errorMessage: "Couldn't save how often GAIA messages you",
    }),
};
