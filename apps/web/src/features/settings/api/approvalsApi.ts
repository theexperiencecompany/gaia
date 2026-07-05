import { apiService } from "@/lib/api/service";

export interface HilPreferences {
  enabled: boolean;
  /** tool name -> should-ask. Holds only user overrides of the default gating. */
  tool_overrides: Record<string, boolean>;
}

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
