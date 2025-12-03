import router from "next/router";
import { apiService } from "@/lib/api";

export interface UserInfo {
  name: string;
  email: string;
  picture: string;
  timezone?: string; // User's timezone
  onboarding?: {
    completed: boolean;
    completed_at?: string;
    preferences?: {
      profession?: string;
      response_style?: string;
      custom_instructions?: string;
    };
  };
  selected_model?: string;
}

export interface GoogleLoginResponse {
  url: string;
}

export const authApi = {
  // Fetch current user info
  fetchUserInfo: async (): Promise<UserInfo> => {
    return apiService.get<UserInfo>("/user/me", {
      silent: true,
    });
  },

  // Initiate Google login
  googleLogin: async (): Promise<GoogleLoginResponse> => {
    return apiService.get<GoogleLoginResponse>("/oauth/login/google", {
      errorMessage: "Failed to initiate Google login",
    });
  },

  // Update user profile (name/picture)
  updateProfile: async (formData: FormData): Promise<UserInfo> => {
    return apiService.patch<UserInfo>("/user/me", formData, {
      successMessage: "Profile updated successfully",
      errorMessage: "Failed to update profile",
    });
  },

  // Update user name only
  updateName: async (name: string): Promise<UserInfo> => {
    const formData = new FormData();
    formData.append("name", name);
    return apiService.patch<UserInfo>("/user/name", formData, {
      successMessage: "Name updated successfully",
      errorMessage: "Failed to update name",
    });
  },

  // Logout user
  logout: async (): Promise<void> => {
    await apiService.post<{ logout_url: string }>(
      "/user/logout",
      {},
      {
        successMessage: "Logged out successfully",
        errorMessage: "Failed to logout",
      },
    );

    // Redirect to the logout URL returned by the backend
    // if (response.logout_url)
    //   window.location.href = response.logout_url;
  },

  // Complete onboarding
  completeOnboarding: async (onboardingData: {
    name: string;
    profession: string;
  }): Promise<{ success: boolean; message: string; user?: UserInfo }> => {
    return apiService.post("/onboarding", onboardingData, {
      successMessage: "Welcome! Your preferences have been saved.",
      errorMessage: "Failed to complete onboarding",
    });
  },

  // Update user preferences (renamed for clarity)
  updateOnboardingPreferences: async (preferences: {
    profession?: string;
    response_style?: string;
    custom_instructions?: string | null;
  }): Promise<{ success: boolean; message: string; user?: UserInfo }> => {
    return apiService.patch("/onboarding/preferences", preferences, {
      silent: true,
    });
  },

  // Update user timezone separately
  updateUserTimezone: async (
    timezone: string,
  ): Promise<{ success: boolean; message: string; timezone: string }> => {
    const formData = new FormData();
    formData.append("timezone", timezone);
    return apiService.patch("/user/timezone", formData, {
      silent: true,
    });
  },
};
