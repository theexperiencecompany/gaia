import { apiService } from "@/lib/api/service";

export interface HilPreferences {
  enabled: boolean;
  always_allowed_tools: string[];
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
};
