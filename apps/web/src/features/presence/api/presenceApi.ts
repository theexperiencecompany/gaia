import { api } from "@/lib/api/typed";

export const presenceApi = {
  holdFocus: () =>
    api.put("/api/v1/presence/focus", { silent: true, background: true }),

  releaseFocus: () =>
    api.delete("/api/v1/presence/focus", { silent: true, background: true }),
};
