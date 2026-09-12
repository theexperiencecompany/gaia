import { api } from "@/lib/api/typed";

export const firstStepsApi = {
  // Every `done` flag is derived server-side; there is no endpoint to set one.
  fetch: () => api.get("/api/v1/user/first-steps", { silent: true }),

  // Both directions persist, so a checklist expanded on one device stays
  // expanded on the next.
  setCollapsed: (collapsed: boolean) =>
    api.post("/api/v1/user/first-steps/collapse", {
      body: { collapsed },
      silent: true,
    }),
};
