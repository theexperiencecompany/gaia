import { api } from "@/lib/api/typed";

export const presenceApi = {
  holdFocus: (clientId: string) =>
    api.put("/api/v1/presence/focus", {
      query: { client_id: clientId },
      silent: true,
      background: true,
    }),

  releaseFocus: (clientId: string) =>
    api.delete("/api/v1/presence/focus", {
      query: { client_id: clientId },
      silent: true,
      background: true,
    }),
};
