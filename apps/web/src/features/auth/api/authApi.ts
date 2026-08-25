import { apiauth } from "@/lib/api/client";
import { apiService } from "@/lib/api/service";

export interface UserInfo {
  user_id: string;
  name: string;
  email: string;
  picture: string;
  timezone?: string;
  onboarding?: {
    completed: boolean;
    completed_at?: string;
    phase?: string;
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

/** Body of POST /auth/login and /auth/signup on success. */
export interface LocalAuthResponse {
  user: UserInfo;
}

interface LocalAuthError {
  status?: number;
  errorCode?: string;
  message?: string;
}

/**
 * Normalizes a failed localLogin/localSignup call into the pieces the auth
 * forms branch on. The backend answers with FastAPI-wrapped bodies —
 * `{ detail: { error_code, message } }` (401 `invalid_credentials`, 403
 * `registration_closed`) or plain `{ detail: "..." }` / `{ message: "..." }`.
 * Same extraction contract as the shapes handled in lib/api/service.ts.
 */
export function getLocalAuthError(error: unknown): LocalAuthError {
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

  // Local (self-host) email/password login. These bypass apiService because
  // the auth forms need the raw HTTP status (401 invalid credentials, 403
  // registration_closed) to render inline errors instead of toasts. The
  // backend sets the session cookie on the response.
  localLogin: async (
    email: string,
    password: string,
  ): Promise<LocalAuthResponse> => {
    const response = await apiauth.post<LocalAuthResponse>(
      `${apiauth.getUri()}auth/login`,
      { email, password },
      { withCredentials: true },
    );
    return response.data;
  },

  localSignup: async (
    name: string | undefined,
    email: string,
    password: string,
  ): Promise<LocalAuthResponse> => {
    const response = await apiauth.post<LocalAuthResponse>(
      `${apiauth.getUri()}auth/signup`,
      // The backend treats an empty/absent name identically; never send "".
      { name: name?.trim() || undefined, email, password },
      { withCredentials: true },
    );
    return response.data;
  },

  // Local (self-host) password change — PATCH /auth/password. Requires a live
  // session; a wrong current password comes back as 401 invalid_credentials
  // which apiService never toasts (it looks like an auth failure), so the
  // caller extracts it with getLocalAuthError and renders it inline.
  changePassword: async (
    currentPassword: string,
    newPassword: string,
  ): Promise<void> => {
    await apiService.patch(
      "/auth/password",
      {
        current_password: currentPassword,
        new_password: newPassword,
      },
      { successMessage: "Password updated successfully" },
    );
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
    const response = await apiService.post<{
      logout_url?: string;
      mode?: string;
    }>(
      "/user/logout",
      {},
      {
        successMessage: "Logged out successfully",
        errorMessage: "Failed to logout",
      },
    );

    // Local-mode (self-host) sessions have no hosted logout page: the backend
    // already cleared the session cookie, and the caller (useLogout) clears
    // all client state right after this resolves. Skip external navigation.
    if (response.mode === "local") {
      return;
    }

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
    name: string;
    profession: string;
    timezone?: string;
    focus?: string;
    clarify_answers?: {
      id: string;
      kind: string;
      question: string;
      value: string | null;
    }[];
    selected_integrations?: string[];
    defer_workflows?: boolean;
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
