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
import { unregisterDeviceOnLogout } from "@/features/notifications";

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: UserInfo | null;
  signOut: () => Promise<void>;
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

  const signOut = useCallback(async () => {
    try {
      // Unregister device token from push notifications
      await unregisterDeviceOnLogout();

      // Clear auth data
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

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

export type { UserInfo } from "@/features/auth/types";
