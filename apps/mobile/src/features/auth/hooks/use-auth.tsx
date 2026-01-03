import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import type { UserInfo } from "@/features/auth/types";
import {
  getAuthToken,
  getUserInfo,
  removeAuthToken,
  removeUserInfo,
} from "@/features/auth/utils/auth-storage";

interface AuthContextType {
  /** Whether the user is authenticated */
  isAuthenticated: boolean;
  /** Whether auth state is being loaded */
  isLoading: boolean;
  /** Current user info if authenticated */
  user: UserInfo | null;
  /** Clear auth state and storage (does NOT navigate - components should handle navigation) */
  signOut: () => Promise<void>;
  /** Refresh auth state from storage */
  refreshAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [user, setUser] = useState<UserInfo | null>(null);

  const checkAuthStatus = useCallback(async () => {
    try {
      const token = await getAuthToken();
      const userInfo = await getUserInfo();
      setIsAuthenticated(!!token);
      setUser(userInfo);
    } catch (error) {
      console.error("Error checking auth status:", error);
      setIsAuthenticated(false);
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuthStatus();
  }, [checkAuthStatus]);

  const refreshAuth = useCallback(async () => {
    try {
      const token = await getAuthToken();
      const userInfo = await getUserInfo();
      setIsAuthenticated(!!token);
      setUser(userInfo);
    } catch (error) {
      console.error("Error refreshing auth status:", error);
      setIsAuthenticated(false);
      setUser(null);
    }
  }, []);

  /**
   * Sign out the user - clears storage and state.
   * NOTE: Navigation should be handled by the calling component,
   * not by this hook. This keeps the hook decoupled from routing.
   */
  const signOut = useCallback(async () => {
    try {
      await removeAuthToken();
      await removeUserInfo();
      setIsAuthenticated(false);
      setUser(null);
    } catch (error) {
      console.error("Error signing out:", error);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{ isAuthenticated, isLoading, user, signOut, refreshAuth }}
    >
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Hook to access auth state and actions.
 * Must be used within an AuthProvider.
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

export type { UserInfo } from "@/features/auth/types";
