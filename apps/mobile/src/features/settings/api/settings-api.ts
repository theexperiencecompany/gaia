import { apiService } from "@/lib/api";
import type {
  UsagePeriod,
  FeatureUsage,
  TokenUsagePeriod,
  TokenUsage,
  UsageSummary,
} from "@gaia/shared/types";

export type {
  UsagePeriod,
  FeatureUsage,
  TokenUsagePeriod,
  TokenUsage,
  UsageSummary,
} from "@gaia/shared/types";

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
  onboarding?: {
    completed: boolean;
    completed_at?: string;
    preferences?: OnboardingPreferences;
  };
  selected_model?: string;
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
};
