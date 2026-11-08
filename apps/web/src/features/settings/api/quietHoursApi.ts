import type { QuietHours } from "@shared/api/generated";
import { api } from "@/lib/api/typed";

export const quietHoursApi = {
  fetch: () => api.get("/api/v1/user/quiet-hours", { silent: true }),

  // Echoes back what was stored.
  update: (hours: QuietHours) =>
    api.patch("/api/v1/user/quiet-hours", {
      body: hours,
      errorMessage: "Couldn't save your quiet hours",
    }),
};
