import { apiService } from "@/lib/api/service";

/**
 * The onboarding block as the API returns it — on `GET /oauth/me` and on the
 * onboarding endpoints. This declaration is the only one: the user store and
 * the personalization payload both borrow their fields from here rather than
 * restating them.
 */
export interface OnboardingData {
  completed: boolean;
  completed_at?: string;
  phase?: string;
  /** The "Getting started" conversation the server seeds on completion. */
  first_message_conversation_id?: string;
  /** The seeded "Getting started" conversation the wizard hands off into. */
  getting_started_conversation_id?: string;
  preferences?: {
    profession?: string;
    /** Onboarding Q2, as stored: the jobs the user handed GAIA. */
    needs?: string[];
    /** Onboarding Q2's "Something else", verbatim. */
    other_need?: string;
    response_style?: string;
    custom_instructions?: string;
  };
}

export interface UserInfo {
  user_id: string;
  name: string;
  email: string;
  picture: string;
  timezone?: string;
  onboarding?: OnboardingData;
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
    const response = await apiService.post<{ logout_url?: string }>(
      "/user/logout",
      {},
      {
        successMessage: "Logged out successfully",
        errorMessage: "Failed to logout",
      },
    );

    // Redirect to the logout URL returned by the backend
    // Validate URL scheme to prevent XSS/open-redirect via javascript:/data: URLs
    if (response.logout_url) {
      try {
        const url = new URL(response.logout_url, window.location.origin);
        if (url.protocol === "https:" || url.protocol === "http:") {
          window.location.href = response.logout_url;
        } else {
          console.error("[authApi] Invalid logout URL scheme:", url.protocol);
        }
      } catch {
        console.error("[authApi] Invalid logout URL:", response.logout_url);
      }
    }
  },

  // Complete onboarding
  completeOnboarding: async (onboardingData: {
    profession: string;
    needs: string[];
    other_need?: string;
    timezone?: string;
  }): Promise<{ success: boolean; message: string; user?: UserInfo }> => {
    return apiService.post("/onboarding", onboardingData, {
      silent: true,
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
