import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert } from "react-native";
import { fetchUserInfo, startOAuthFlow } from "@/features/auth";
import { AuthScreen } from "@/features/auth/components/auth-screen";
import { useAuth } from "@/features/auth/hooks/use-auth";
import {
  storeAuthToken,
  storeUserInfo,
} from "@/features/auth/utils/auth-storage";

export default function SignUpScreen() {
  const router = useRouter();
  const { refreshAuth } = useAuth();
  const [isLoading, setIsLoading] = useState(false);

  const handleSignUp = async () => {
    setIsLoading(true);
    try {
      const token = await startOAuthFlow();
      await storeAuthToken(token);
      const userInfo = await fetchUserInfo(token);
      await storeUserInfo(userInfo);
      await refreshAuth();
      router.replace("/");
    } catch (error) {
      console.error("Sign up error:", error);
      Alert.alert(
        "Sign Up Failed",
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
      title="Time to Supercharge You."
      buttonLabel="Sign up with Google"
      footerQuestion="Already have an account?"
      footerLinkLabel="Sign in"
      isLoading={isLoading}
      onSubmit={() => void handleSignUp()}
      onFooterLinkPress={() => router.push("/login")}
    />
  );
}
