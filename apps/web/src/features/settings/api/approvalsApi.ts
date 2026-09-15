import type { HilPreferences } from "@shared/chat";
import { api } from "@/lib/api/typed";

export type { HilPreferences };

// `silent: true` on the mutations suppresses the generic toast, NOT the failure:
// each already has a specific one — the mode caller catches setMode ("Failed to
// update approval mode"), and overrideMutation.onError covers the per-tool save.
// Without it a failed save toasts twice.
export const approvalsApi = {
  getHilPreferences: () =>
    api.get("/api/v1/approvals/preferences", { silent: true }),

  putHilPreferences: (payload: Partial<HilPreferences>) =>
    api.put("/api/v1/approvals/preferences", { body: payload, silent: true }),

  // ask: true = always ask, false = never ask, null = clear override (use default).
  setToolOverride: (toolName: string, ask: boolean | null) =>
    api.put("/api/v1/approvals/tools/{tool_name}", {
      path: { tool_name: toolName },
      body: { ask },
      silent: true,
    }),
};
