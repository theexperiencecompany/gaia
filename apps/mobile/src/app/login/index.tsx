import { useRouter } from "expo-router";
import { Button, PressableFeedback } from "heroui-native";
import { useState } from "react";
import { ActivityIndicator, Alert, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import {
  AuthCard,
  AuthLogo,
  AuthScreenLayout,
} from "@/features/auth/components/AuthScreenLayout";
import {
  fetchUserInfo,
  startOAuthFlow,
} from "@/features/auth/utils/auth-service";
import {
  storeAuthToken,
  storeUserInfo,
} from "@/features/auth/utils/auth-storage";
import { useResponsive } from "@/lib/responsive";

export default function LoginScreen() {
  const router = useRouter();
  const { refreshAuth } = useAuth();
  const [isLoading, setIsLoading] = useState(false);
  const { spacing, fontSize } = useResponsive();

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
    <AuthScreenLayout
      backgroundSource={require("@/assets/background/login.webp")}
    >
      <AuthCard>
        {/* Logo and Title */}
        <View style={{ alignItems: "center", marginBottom: spacing.xl }}>
          <AuthLogo />
          <Text
            style={{
              fontSize: fontSize["2xl"],
              fontWeight: "bold",
              textAlign: "center",
            }}
          >
            Let's Get You Back In
          </Text>
        </View>

        {/* Login Form */}
        <View style={{ width: "100%" }}>
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
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              marginTop: spacing.md,
            }}
          >
            <Text style={{ fontSize: fontSize.base, color: "#8e8e93" }}>
              Don't have an account?{" "}
            </Text>
            <PressableFeedback onPress={handleSignUp} isDisabled={isLoading}>
              <Text
                style={{
                  fontSize: fontSize.base,
                  color: "#00bbff",
                  fontWeight: "600",
                }}
              >
                Sign up
              </Text>
            </PressableFeedback>
          </View>
        </View>

        {/* Footer */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
            marginTop: spacing.lg,
            flexWrap: "wrap",
          }}
        >
          <PressableFeedback>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#8e8e93",
                textDecorationLine: "underline",
              }}
            >
              Terms of Service
            </Text>
          </PressableFeedback>
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#8e8e93",
              marginHorizontal: spacing.xs,
            }}
          >
            and
          </Text>
          <PressableFeedback>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: "#8e8e93",
                textDecorationLine: "underline",
              }}
            >
              Privacy Policy
            </Text>
          </PressableFeedback>
        </View>
      </AuthCard>
    </AuthScreenLayout>
  );
}
