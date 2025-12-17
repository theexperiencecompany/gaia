/**
 * Auth Hook
 * Manages authentication state and provides auth utilities
 */

import { useRouter, useSegments } from "expo-router";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  getAuthToken,
  getUserInfo,
  removeAuthToken,
  removeUserInfo,
  type UserInfo,
} from "@/shared/utils/auth-storage";

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: UserInfo | null;
  signOut: () => Promise<void>;
  refreshAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [user, setUser] = useState<UserInfo | null>(null);
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    checkAuthStatus();
  }, []);

  useEffect(() => {
    if (isLoading) return;

    const inAuthGroup = segments[0] === "login" || segments[0] === "signup";

    if (!isAuthenticated && !inAuthGroup) {
      // Redirect to login if not authenticated
      router.replace("/login");
    } else if (isAuthenticated && inAuthGroup) {
      // Redirect to main app if authenticated
      router.replace("/(tabs)");
    }
  }, [isAuthenticated, segments, isLoading, router]);

  const checkAuthStatus = async () => {
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
  };

  const refreshAuth = async () => {
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
  };

  const signOut = async () => {
    try {
      await removeAuthToken();
      await removeUserInfo();
      setIsAuthenticated(false);
      setUser(null);
      router.replace("/auth/login");
    } catch (error) {
      console.error("Error signing out:", error);
    }
  };

  return (
    <AuthContext.Provider
      value={{ isAuthenticated, isLoading, user, signOut, refreshAuth }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
