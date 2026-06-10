/**
 * Maps the API `UserInfo` shape (snake_case fields, `picture`) to the user
 * store shape (camelCase, `profilePicture`). Single conversion site so any
 * caller hydrating the store from a server response stays consistent.
 */

import type { UserInfo } from "../api/authApi";

export interface StoreUser {
  userId: string;
  name: string;
  email: string;
  profilePicture: string;
  timezone: string | undefined;
  onboarding: UserInfo["onboarding"];
  selected_model: string | undefined;
}

export function userInfoToStoreUser(info: UserInfo): StoreUser {
  return {
    userId: info.user_id,
    name: info.name,
    email: info.email,
    profilePicture: info.picture,
    timezone: info.timezone,
    onboarding: info.onboarding,
    selected_model: info.selected_model,
  };
}
