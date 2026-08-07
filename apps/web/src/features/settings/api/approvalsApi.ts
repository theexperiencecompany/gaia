import type { HilPreferences } from "@shared/chat";
import { apiService } from "@/lib/api/service";

export type { HilPreferences };

// `silent: true` on the mutations suppresses the generic toast, NOT the failure:
// each already has a specific one — the mode caller catches setMode ("Failed to
// update approval mode"), and overrideMutation.onError covers the per-tool save.
// Without it a failed save toasts twice.
export const approvalsApi = {
  getHilPreferences: (): Promise<HilPreferences> =>
    apiService.get<HilPreferences>("/approvals/preferences", { silent: true }),

  putHilPreferences: (
    payload: Partial<HilPreferences>,
  ): Promise<HilPreferences> =>
    apiService.put<HilPreferences>("/approvals/preferences", payload, {
      silent: true,
    }),

  // ask: true = always ask, false = never ask, null = clear override (use default).
  setToolOverride: (
    toolName: string,
    ask: boolean | null,
  ): Promise<HilPreferences> =>
    apiService.put<HilPreferences>(
      `/approvals/tools/${encodeURIComponent(toolName)}`,
      { ask },
      { silent: true },
    ),
};
