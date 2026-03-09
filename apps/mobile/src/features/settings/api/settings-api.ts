import { apiService } from "@/lib/api";

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

export interface UsagePeriod {
  used: number;
  limit: number;
  percentage: number;
  reset_time?: string;
  remaining: number;
}

export interface FeatureUsage {
  title: string;
  description: string;
  category: string;
  periods: {
    hour?: UsagePeriod;
    day?: UsagePeriod;
    month?: UsagePeriod;
  };
}

export interface TokenUsagePeriod {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  limit: number;
  percentage: number;
  remaining: number;
}

export interface TokenUsage {
  title: string;
  periods: {
    day?: TokenUsagePeriod;
    month?: TokenUsagePeriod;
  };
}

export interface UsageSummary {
  user_id: string;
  plan_type: string;
  features: Record<string, FeatureUsage>;
  token_usage: Record<string, TokenUsage>;
  last_updated: string;
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
