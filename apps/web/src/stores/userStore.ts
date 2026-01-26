import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import { useShallow } from "zustand/react/shallow";

export interface OnboardingData {
  completed: boolean;
  completed_at?: string;
  preferences?: {
    profession?: string;
    response_style?: string;
    custom_instructions?: string;
  };
}

interface UserState {
  userId: string;
  profilePicture: string;
  name: string;
  email: string;
  timezone?: string;
  onboarding?: OnboardingData;
  selected_model?: string;
}

interface UserActions {
  setUser: (user: UserState) => void;
  updateUser: (updates: Partial<UserState>) => void;
  clearUser: () => void;
}

type UserStore = UserState & UserActions;

const initialState: UserState = {
  userId: "",
  profilePicture: "",
  name: "",
  email: "",
  timezone: undefined,
  onboarding: undefined,
  selected_model: undefined,
};

export const useUserStore = create<UserStore>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,

        setUser: (user) => set(user, false, "setUser"),

        updateUser: (updates) =>
          set((state) => ({ ...state, ...updates }), false, "updateUser"),

        clearUser: () => set(initialState, false, "clearUser"),
      }),
      {
        name: "user-storage",
        partialize: (state) => ({
          userId: state.userId,
          profilePicture: state.profilePicture,
          name: state.name,
          email: state.email,
          timezone: state.timezone,
          onboarding: state.onboarding,
          selected_model: state.selected_model,
        }),
      },
    ),
    { name: "user-store" },
  ),
);

// Selectors
export const useUserProfile = () =>
  useUserStore(
    useShallow((state) => ({
      profilePicture: state.profilePicture,
      name: state.name,
      email: state.email,
    })),
  );

export const useUserOnboarding = () =>
  useUserStore((state) => state.onboarding);
export const useUserTimezone = () => useUserStore((state) => state.timezone);
