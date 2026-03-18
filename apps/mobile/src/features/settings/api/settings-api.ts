import type { FeatureUsage, UsageSummary } from "@gaia/shared/types";
import { apiService } from "@/lib/api";

export type {
  FeatureUsage,
  TokenUsage,
  TokenUsagePeriod,
  UsagePeriod,
  UsageSummary,
} from "@gaia/shared/types";

export interface UsageHistoryEntry {
  date: string;
  plan_type: string;
  features: Record<string, Pick<FeatureUsage, "title" | "periods">>;
}

export interface OnboardingPreferences {
  profession?: string;
  response_style?: string;
  custom_instructions?: string | null;
}

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

export interface ChannelPreferences {
  telegram: boolean;
  discord: boolean;
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

  getChannelPreferences(): Promise<ChannelPreferences> {
    return apiService.get<ChannelPreferences>(
      "/notifications/preferences/channels",
    );
  },

  updateChannelPreference(
    platform: "telegram" | "discord",
    enabled: boolean,
  ): Promise<UpdatePreferencesResponse> {
    return apiService.put<UpdatePreferencesResponse>(
      "/notifications/preferences/channels",
      { [platform]: enabled },
    );
  },

  updateHoloCardColors(colors: HoloCardColors): Promise<UserProfile> {
    return apiService.patch<UserProfile>("/user/holo-card/colors", colors);
  },

  getUserStats(): Promise<UserStats> {
    return apiService.get<UserStats>("/user/stats");
  },
};
