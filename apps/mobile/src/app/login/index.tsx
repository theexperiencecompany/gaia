import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert } from "react-native";
import { fetchUserInfo, startOAuthFlow } from "@/features/auth/api/auth-api";
import { AuthScreen } from "@/features/auth/components/auth-screen";
import { useAuth } from "@/features/auth/hooks/use-auth";
import {
  storeAuthToken,
  storeUserInfo,
} from "@/features/auth/utils/auth-storage";

export default function LoginScreen() {
  const router = useRouter();
  const { refreshAuth } = useAuth();
  const [isLoading, setIsLoading] = useState(false);

  const handleLogin = async () => {
    setIsLoading(true);
    try {
      const token = await startOAuthFlow();
      await storeAuthToken(token);
      const userInfo = await fetchUserInfo(token);
      await storeUserInfo(userInfo);
      await refreshAuth();
      router.replace("/");
    } catch (error) {
      console.error("Login error:", error);
      Alert.alert(
        "Login Failed",
        error instanceof Error
          ? error.message
          : "An unexpected error occurred. Please try again.",
        [{ text: "OK" }],
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthScreen
      title="Let's Get You Back In"
      buttonLabel="Sign in with Google"
      footerQuestion="Don't have an account?"
      footerLinkLabel="Sign up"
      isLoading={isLoading}
      onSubmit={() => void handleLogin()}
      onFooterLinkPress={() => router.push("/signup")}
    />
  );
}
