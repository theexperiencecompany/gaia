import type {
  InstructionsResponse,
  OnboardingPreferences,
  UpdateInstructionsRequest,
  UsageHistoryEntry,
} from "@gaia/shared/api/generated";

export type {
  InstructionsResponse,
  OnboardingPreferences,
  UsageHistoryEntry,
} from "@gaia/shared/api/generated";

import type { HilPreferences, HilPreferencesUpdate } from "@gaia/shared/chat";
import { INSTRUCTIONS_CONFLICT_CODE } from "@gaia/shared/constants/instructions";
import type { UsageSummary } from "@gaia/shared/types";
import type { SaveInstructionsResult } from "@/features/settings/types";
import { ApiError, apiService } from "@/lib/api";

export type {
  BudgetWindow,
  FeatureUsage,
  UsagePeriod,
  UsageSummary,
} from "@gaia/shared/types";

export interface UpdatePreferencesResponse {
  success: boolean;
  message: string;
}

export interface UserProfile {
  user_id: string;
  name: string;
  email: string;
  picture: string;
  timezone?: string;
  created_at?: string;
  onboarding?: {
    completed: boolean;
    completed_at?: string;
    preferences?: OnboardingPreferences;
  };
  selected_model?: string;
}

export interface HoloCardColors {
  accent: string;
  gradient_from: string;
  gradient_to: string;
}

export interface UserStats {
  conversation_count: number;
  workflow_count: number;
  integration_count: number;
}

const HTTP_CONFLICT = 409;

function instructionsPath(scope: string): string {
  return `/instructions/${encodeURIComponent(scope)}`;
}

export const settingsApi = {
  getProfile(): Promise<UserProfile> {
    return apiService.get<UserProfile>("/user/me");
  },

  updateProfile(form: FormData): Promise<UserProfile> {
    return apiService.patch<UserProfile>("/user/me", form);
  },

  updatePreferences(
    preferences: OnboardingPreferences,
  ): Promise<UpdatePreferencesResponse> {
    return apiService.patch<UpdatePreferencesResponse>(
      "/onboarding/preferences",
      preferences,
    );
  },

  updateTimezone(timezone: string): Promise<UpdatePreferencesResponse> {
    const form = new FormData();
    form.append("timezone", timezone);
    return apiService.patch<UpdatePreferencesResponse>("/user/timezone", form);
  },

  getInstructions(scope: string): Promise<InstructionsResponse> {
    return apiService.get<InstructionsResponse>(instructionsPath(scope));
  },

  /** Save one scope's instructions; a stale base_revision resolves to a conflict carrying the current revision. */
  async updateInstructions(
    scope: string,
    request: UpdateInstructionsRequest,
  ): Promise<SaveInstructionsResult> {
    try {
      const instructions = await apiService.put<InstructionsResponse>(
        instructionsPath(scope),
        request,
      );
      return { status: "saved", instructions };
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === HTTP_CONFLICT &&
        error.code === INSTRUCTIONS_CONFLICT_CODE &&
        typeof error.envelope?.current_revision === "number"
      ) {
        return {
          status: "conflict",
          currentRevision: error.envelope.current_revision,
        };
      }
      throw error;
    }
  },

  getUsageSummary(): Promise<UsageSummary> {
    return apiService.get<UsageSummary>("/usage/summary");
  },

  getUsageHistory(days = 7, featureKey?: string): Promise<UsageHistoryEntry[]> {
    const params = new URLSearchParams({ days: days.toString() });
    if (featureKey) {
      params.append("feature_key", featureKey);
    }
    return apiService.get<UsageHistoryEntry[]>(`/usage/history?${params}`);
  },

  updateHoloCardColors(colors: HoloCardColors): Promise<UserProfile> {
    return apiService.patch<UserProfile>("/user/holo-card/colors", colors);
  },

  getUserStats(): Promise<UserStats> {
    return apiService.get<UserStats>("/user/stats");
  },

  getHilPreferences(): Promise<HilPreferences> {
    return apiService.get<HilPreferences>("/approvals/preferences");
  },

  updateHilPreferences(payload: HilPreferencesUpdate): Promise<HilPreferences> {
    return apiService.put<HilPreferences>("/approvals/preferences", payload);
  },

  // ask: true = always ask, false = never ask, null = clear override (use default).
  // approvalKey is the server-issued HIL key (tool_overrides key / approval_key).
  setToolOverride(
    approvalKey: string,
    ask: boolean | null,
  ): Promise<HilPreferences> {
    return apiService.put<HilPreferences>(
      `/approvals/tools/${encodeURIComponent(approvalKey)}`,
      { ask },
    );
  },
};
