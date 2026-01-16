import { useRouter } from "expo-router";
import { Button, PressableFeedback } from "heroui-native";
import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  KeyboardAvoidingView,
  Platform,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import {
  fetchUserInfo,
  startOAuthFlow,
} from "@/features/auth/utils/auth-service";
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

  const handleSignUp = () => {
    router.push("/signup");
  };

  return (
    <View className="flex-1 bg-background">
      {/* Full Background Image */}
      <Image
        source={require("@/assets/background/login.webp")}
        className="absolute w-full h-full"
        resizeMode="cover"
        blurRadius={0.5}
      />

      {/* Dark Overlay */}
      <View className="absolute w-full h-full bg-black/50" />

      <SafeAreaView style={{ flex: 1 }}>
        <KeyboardAvoidingView
          className="flex-1 justify-center items-center px-6"
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          {/* Login Card */}
          <View className="w-full max-w-md bg-surface/95 rounded-3xl px-8 py-10 border border-border/20">
            {/* Logo and Title */}
            <View className="items-center mb-8">
              <View className="w-18 h-18 rounded-full bg-accent/15 items-center justify-center mb-4">
                <Image
                  source={require("@shared/assets/logo/logo.webp")}
                  className="w-12 h-12"
                  resizeMode="contain"
                />
              </View>
              <Text className="text-2xl font-bold text-center">
                Let's Get You Back In
              </Text>
            </View>

            {/* Login Form */}
            <View className="w-full">
              {/* Login Button */}
              <Button
                size="lg"
                className="bg-accent"
                isDisabled={isLoading}
                onPress={handleLogin}
              >
                {isLoading ? (
                  <ActivityIndicator colorClassName="accent-black" />
                ) : (
                  <Button.Label>Continue with WorkOS</Button.Label>
                )}
              </Button>

              {/* Sign Up Link */}
              <View className="flex-row items-center justify-center mt-4">
                <Text className="text-base text-muted">
                  Don't have an account?{" "}
                </Text>
                <PressableFeedback
                  onPress={handleSignUp}
                  isDisabled={isLoading}
                >
                  <Text className="text-base text-accent font-semibold">
                    Sign up
                  </Text>
                </PressableFeedback>
              </View>
            </View>

            {/* Footer */}
            <View className="flex-row items-center justify-center mt-6 flex-wrap">
              <PressableFeedback>
                <Text className="text-sm text-muted underline">
                  Terms of Service
                </Text>
              </PressableFeedback>
              <Text className="text-sm text-muted mx-1"> and </Text>
              <PressableFeedback>
                <Text className="text-sm text-muted underline">
                  Privacy Policy
                </Text>
              </PressableFeedback>
            </View>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
