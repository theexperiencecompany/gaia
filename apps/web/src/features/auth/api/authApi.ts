import { ApiError } from "@shared/api";
import type {
  AuthenticatedUserResponse,
  OnboardingPreferences,
  OnboardingRequest,
  OnboardingStatusResponse,
} from "@shared/api/generated";
import {
  type ApiBody,
  api,
  FORM_URLENCODED_HEADERS,
  formDataSerializer,
} from "@/lib/api/typed";

/** The onboarding block as `GET /user/me` and the onboarding endpoints return it. */
export type OnboardingData = OnboardingStatusResponse;

/** `GET /user/me`. */
export type UserInfo = AuthenticatedUserResponse;

/**
 * Normalizes a failed localLogin/localSignup/changePassword call into the
 * pieces the auth forms branch on: the HTTP status plus the `ErrorEnvelope`'s
 * `code` (401 `invalid_credentials`, 403 `registration_closed` /
 * `invite_invalid`) and `message`.
 */
export function getLocalAuthError(error: unknown): {
  status?: number;
  errorCode?: string;
  message?: string;
} {
  if (!(error instanceof ApiError)) return {};
  return {
    status: error.status,
    errorCode: error.code,
    message: error.envelope?.message ?? undefined,
  };
}

export const authApi = {
  // Fetch current user info
  fetchUserInfo: () => api.get("/api/v1/user/me", { silent: true }),

  // Local (self-host) sign-in and sign-up render their failures inline.
  localLogin: (email: string, password: string) =>
    api.post("/api/v1/auth/login", {
      body: { email, password },
      silent: true,
    }),

  localSignup: (
    name: string | undefined,
    email: string,
    password: string,
    invite: string | undefined,
  ) =>
    api.post("/api/v1/auth/signup", {
      // The backend treats an empty/absent name identically; never send "".
      body: { name: name?.trim() || undefined, email, password, invite },
      silent: true,
    }),

  // A 401 (wrong current password) is never toasted; the caller renders it.
  changePassword: (currentPassword: string, newPassword: string) =>
    api.patch("/api/v1/auth/password", {
      body: { current_password: currentPassword, new_password: newPassword },
      successMessage: "Password updated successfully",
    }),

  // Update user profile (name/picture)
  updateProfile: (body: ApiBody<"patch", "/api/v1/user/me">) =>
    api.patch("/api/v1/user/me", {
      body,
      bodySerializer: formDataSerializer,
      successMessage: "Profile updated successfully",
      errorMessage: "Failed to update profile",
    }),

  // Update user name only
  updateName: (name: string) =>
    api.patch("/api/v1/user/name", {
      body: { name },
      headers: FORM_URLENCODED_HEADERS,
      successMessage: "Name updated successfully",
      errorMessage: "Failed to update name",
    }),

  // Logout user
  logout: async (): Promise<void> => {
    const response = await api.post("/api/v1/user/logout", {
      successMessage: "Logged out successfully",
      errorMessage: "Failed to logout",
    });

    // Local sessions answer `{"mode": "local"}` with no logout_url — the check
    // below covers both modes.
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
  completeOnboarding: (onboardingData: OnboardingRequest) =>
    api.post("/api/v1/onboarding", { body: onboardingData, silent: true }),

  // Update user preferences (renamed for clarity)
  updateOnboardingPreferences: (preferences: OnboardingPreferences) =>
    api.patch("/api/v1/onboarding/preferences", {
      body: preferences,
      silent: true,
    }),

  // Update user timezone separately
  updateUserTimezone: (timezone: string) =>
    api.patch("/api/v1/user/timezone", {
      body: { timezone },
      headers: FORM_URLENCODED_HEADERS,
      silent: true,
    }),
};
