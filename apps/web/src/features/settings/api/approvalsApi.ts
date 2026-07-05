import type { HilPreferences } from "@shared/chat";
import { apiService } from "@/lib/api/service";

export type { HilPreferences };

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
