/**
 * Local (self-host) credential endpoints — `POST /auth/login`,
 * `POST /auth/signup`, `PATCH /auth/password`.
 *
 * These three are the only GAIA API routes the path-typed client cannot call:
 * the whole `/auth` router mounts ONLY under `AUTH_MODE=local`
 * (`app/api/v1/routes.py`), so a schema generated from a WorkOS instance never
 * declares them and `api.post` has no `paths` entry to accept — the same
 * situation `features/team/api/teamApi.ts` documents.
 *
 * So they go through the axios instance directly, which also buys the callers
 * what they need: the raw HTTP status (401 `invalid_credentials`, 403
 * `registration_closed`) to render an inline error instead of a toast, and the
 * app-shell error handler's 429/5xx toasts. The backend sets the session
 * cookie on each response.
 *
 * Feature code calls this through `features/auth/api/authApi` and normalizes
 * the failure with `getLocalAuthError`.
 */

import { apiauth } from "./client";
import { type ApiOptions, announceSuccess } from "./outcome";

/** The identity block a successful local login/signup returns. */
export type LocalAuthUser = Record<string, unknown>;

/** What both credential endpoints answer with on success. */
export interface LocalAuthResponse {
  user: LocalAuthUser;
}

// Relative to apiauth's baseURL; axios inserts the separator.
const authUrl = (path: string): string => `auth/${path}`;

export const localAuthApi = {
  login: async (
    email: string,
    password: string,
    options: ApiOptions,
  ): Promise<LocalAuthResponse> => {
    const response = await apiauth.post<LocalAuthResponse>(
      authUrl("login"),
      { email, password },
      { withCredentials: true },
    );
    announceSuccess(options);
    return response.data;
  },

  signup: async (
    name: string | undefined,
    email: string,
    password: string,
    invite: string | undefined,
    options: ApiOptions,
  ): Promise<LocalAuthResponse> => {
    const response = await apiauth.post<LocalAuthResponse>(
      authUrl("signup"),
      // The backend treats an empty/absent name identically; never send "".
      { name: name?.trim() || undefined, email, password, invite },
      { withCredentials: true },
    );
    announceSuccess(options);
    return response.data;
  },

  changePassword: async (
    currentPassword: string,
    newPassword: string,
    options: ApiOptions,
  ): Promise<void> => {
    await apiauth.patch(
      authUrl("password"),
      {
        current_password: currentPassword,
        new_password: newPassword,
      },
      { withCredentials: true },
    );
    announceSuccess(options);
  },
};
