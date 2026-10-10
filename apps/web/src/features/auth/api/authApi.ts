import type {
  AuthenticatedUserResponse,
  OnboardingPreferences,
  OnboardingRequest,
  OnboardingStatusResponse,
} from "@shared/api/generated";
import { localAuthApi } from "@/lib/api/localAuth";
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
 * pieces the auth forms branch on. The backend answers with FastAPI-wrapped
 * bodies — `{ detail: { error_code, message } }` (401 `invalid_credentials`,
 * 403 `registration_closed`) or plain `{ detail: "..." }` / `{ message: "..." }`.
 * Same extraction contract as the shapes handled in lib/api/outcome.ts.
 */
export function getLocalAuthError(error: unknown): {
  status?: number;
  errorCode?: string;
  message?: string;
} {
  const response = (
    error as { response?: { status?: number; data?: unknown } } | undefined
  )?.response;
  const data = response?.data as
    | {
        detail?: { error_code?: string; message?: string } | string;
        message?: string;
      }
    | undefined;

  const detail = data?.detail;
  return {
    status: response?.status,
    errorCode:
      typeof detail === "object" && detail !== null
        ? detail.error_code
        : undefined,
    message:
      (typeof detail === "object" && detail !== null
        ? detail.message
        : typeof detail === "string"
          ? detail
          : undefined) ?? data?.message,
  };
}

// Local-auth calls delegate to lib/api/localAuth: those paths mount only under
// AUTH_MODE=local, so the generated contract omits them.
export const authApi = {
  // Fetch current user info
  fetchUserInfo: () => api.get("/api/v1/user/me", { silent: true }),

  // Local (self-host) email/password login.
  localLogin: (email: string, password: string) =>
    localAuthApi.login(email, password, {}),

  localSignup: (name: string | undefined, email: string, password: string) =>
    localAuthApi.signup(name, email, password, {}),

  // Wrong current password 401s as invalid_credentials, never toasted — the
  // caller extracts it with getLocalAuthError and renders it inline.
  changePassword: (currentPassword: string, newPassword: string) =>
    localAuthApi.changePassword(currentPassword, newPassword, {
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
