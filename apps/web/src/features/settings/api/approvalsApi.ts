import type { HilPreferencesUpdate } from "@shared/chat";
import { api } from "@/lib/api/typed";

// `silent: true` on mutations suppresses the generic toast, NOT the failure —
// each already has a specific one (setMode's caller, overrideMutation.onError)
// — without it a failed save toasts twice.
export const approvalsApi = {
  getHilPreferences: () =>
    api.get("/api/v1/approvals/preferences", { silent: true }),

  putHilPreferences: (payload: HilPreferencesUpdate) =>
    api.put("/api/v1/approvals/preferences", { body: payload, silent: true }),

  // ask: true = always ask, false = never ask, null = clear override (use default).
  // approvalKey is the server-issued HIL key (tool_overrides key / approval_key).
  setToolOverride: (approvalKey: string, ask: boolean | null) =>
    api.put("/api/v1/approvals/tools/{tool_name}", {
      path: { tool_name: approvalKey },
      body: { ask },
      silent: true,
    }),
};
