/**
 * Maps the API `UserInfo` shape (snake_case fields, `picture`) to the shape the
 * UI reads (camelCase, `profilePicture`). Single conversion site, used as the
 * `select` of the `["current-user"]` query.
 */

import type { UserInfo } from "../api/authApi";

export interface CurrentUser {
  userId: string;
  name: string;
  email: string;
  profilePicture: string;
  timezone: string | undefined;
  onboarding: UserInfo["onboarding"] | undefined;
}

export function toCurrentUser(info: UserInfo): CurrentUser {
  return {
    userId: info.user_id,
    name: info.name ?? "",
    email: info.email ?? "",
    profilePicture: info.picture ?? "",
    timezone: info.timezone ?? undefined,
    onboarding: info.onboarding,
  };
}
