import type { Schema } from "@shared/api/generated";
import { api } from "@/lib/api/typed";

/** The onboarding block as `GET /user/me` and the onboarding endpoints return it. */
export type OnboardingData = Schema<"OnboardingStatusResponse">;

/** `GET /user/me`. */
export type UserInfo = Schema<"AuthenticatedUserResponse">;

export const authApi = {
  // Fetch current user info
  fetchUserInfo: () => api.get("/api/v1/user/me", { silent: true }),

  // Update user profile (name/picture)
  updateProfile: (formData: FormData) =>
    api.patch("/api/v1/user/me", {
      body: formData,
      successMessage: "Profile updated successfully",
      errorMessage: "Failed to update profile",
    }),

  // Update user name only
  updateName: (name: string) =>
    api.patch("/api/v1/user/name", {
      body: new URLSearchParams({ name }),
      successMessage: "Name updated successfully",
      errorMessage: "Failed to update name",
    }),

  // Logout user
  logout: async (): Promise<void> => {
    const response = await api.post("/api/v1/user/logout", {
      successMessage: "Logged out successfully",
      errorMessage: "Failed to logout",
    });

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
  completeOnboarding: (onboardingData: Schema<"OnboardingRequest">) =>
    api.post("/api/v1/onboarding", { body: onboardingData, silent: true }),

  // Update user preferences (renamed for clarity)
  updateOnboardingPreferences: (preferences: Schema<"OnboardingPreferences">) =>
    api.patch("/api/v1/onboarding/preferences", {
      body: preferences,
      silent: true,
    }),

  // Update user timezone separately
  updateUserTimezone: (timezone: string) =>
    api.patch("/api/v1/user/timezone", {
      body: new URLSearchParams({ timezone }),
      silent: true,
    }),
};
