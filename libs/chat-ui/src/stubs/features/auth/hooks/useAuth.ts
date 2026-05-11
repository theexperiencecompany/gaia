/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import { useUser, type User } from "./useUser";

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

export function useAuth(): AuthState {
  const user = useUser();
  return {
    user: user ?? null,
    isAuthenticated: !!user?.userId,
    isLoading: false,
  };
}
