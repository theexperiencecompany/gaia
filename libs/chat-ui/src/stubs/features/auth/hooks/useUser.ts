/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
export interface OnboardingData {
  completed: boolean;
  completed_at?: string;
  preferences?: {
    profession?: string;
    response_style?: string;
    custom_instructions?: string;
  };
}

export interface User {
  userId: string;
  profilePicture: string | undefined;
  name: string;
  email: string;
  timezone?: string;
  onboarding?: OnboardingData;
  selected_model?: string;
}

export interface UserActions {
  setUser: (user: User) => void;
  updateUser: (updates: Partial<User>) => void;
  clearUser: () => void;
}

const noop = () => {};

const defaultUser: User & UserActions = Object.freeze({
  userId: "",
  profilePicture: undefined,
  name: "",
  email: "",
  timezone: undefined,
  onboarding: undefined,
  selected_model: undefined,
  setUser: noop,
  updateUser: noop,
  clearUser: noop,
});

export const useUser = (): User & UserActions => defaultUser;

export const useUserActions = (): UserActions => ({
  setUser: noop,
  updateUser: noop,
  clearUser: noop,
});
