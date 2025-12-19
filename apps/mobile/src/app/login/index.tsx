import { useRouter } from "expo-router";
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
import { Button } from "@/components/ui/button";
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
      // Start OAuth flow and get token
      const token = await startOAuthFlow();

      // Store the authentication token
      await storeAuthToken(token);

      // Fetch and store user information
      const userInfo = await fetchUserInfo(token);
      await storeUserInfo(userInfo);

      // Refresh auth state to trigger navigation
      await refreshAuth();

      // Navigate to main app
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
    <View className="flex-1 bg-[#0a1929]">
      {/* Full Background Image */}
      <Image
        source={require("@/assets/background/login.webp")}
        className="absolute w-full h-full"
        resizeMode="cover"
        blurRadius={0.5}
        fadeDuration={300}
      />

      {/* Dark Overlay */}
      <View className="absolute w-full h-full bg-black/50" />

      <SafeAreaView className="flex-1">
        <KeyboardAvoidingView
          className="flex-1 justify-center items-center px-6"
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          {/* Login Card */}
          <View className="w-full max-w-[450px] bg-[#1a1a1a]/95 rounded-[20px] px-8 py-10 border border-white/10 shadow-2xl elevation-20">
            {/* Logo and Title */}
            <View className="items-center mb-8">
              <View className="w-[70px] h-[70px] rounded-full bg-[#16c1ff]/15 items-center justify-center mb-4">
                <Image
                  source={require("@/assets/logo/logo.webp")}
                  className="w-[50px] h-[50px]"
                  resizeMode="contain"
                />
              </View>
              <Text className="text-2xl font-bold text-white text-center">
                Let&apos;s Get You Back In
              </Text>
            </View>

            {/* Login Form */}
            <View className="w-full">
              {/* Login Button */}
              <Button
                size="lg"
                className="bg-[#16c1ff] rounded-xl mb-4 shadow-lg shadow-[#16c1ff]/40 elevation-8 min-h-[48px]"
                onPress={handleLogin}
                disabled={isLoading}
              >
                {isLoading ? (
                  <ActivityIndicator color="#000000" />
                ) : (
                  <Text className="text-base font-semibold text-black">
                    Continue with WorkOS
                  </Text>
                )}
              </Button>

              {/* Sign Up Link */}
              <View className="flex-row items-center justify-center mt-4">
                <Text className="text-base text-zinc-400">
                  Don&apos;t have an account?{" "}
                </Text>
                <Button
                  variant="link"
                  size="sm"
                  onPress={handleSignUp}
                  disabled={isLoading}
                  className="p-0 h-auto"
                >
                  <Text className="text-base text-[#16c1ff] font-semibold">
                    Sign up
                  </Text>
                </Button>
              </View>
            </View>

            {/* Footer */}
            <View className="flex-row items-center justify-center mt-6 flex-wrap">
              <Button variant="link" size="sm" className="p-0 h-auto">
                <Text className="text-sm text-zinc-400 underline">
                  Terms of Service
                </Text>
              </Button>
              <Text className="text-sm text-zinc-400 mx-1"> and </Text>
              <Button variant="link" size="sm" className="p-0 h-auto">
                <Text className="text-sm text-zinc-400 underline">
                  Privacy Policy
                </Text>
              </Button>
            </View>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
