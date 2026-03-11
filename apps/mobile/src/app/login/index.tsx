import { useRouter } from "expo-router";
import { Button, Card, PressableFeedback, Spinner } from "heroui-native";
import { useState } from "react";
import {
  Alert,
  Image,
  KeyboardAvoidingView,
  Platform,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import { fetchUserInfo, startOAuthFlow } from "@/features/auth";
import { useAuth } from "@/features/auth/hooks/use-auth";
import {
  storeAuthToken,
  storeUserInfo,
} from "@/features/auth/utils/auth-storage";
import { useResponsive } from "@/lib/responsive";

const loginBackgroundSource =
  process.env.NODE_ENV === "test"
    ? { uri: "login-background" }
    : require("@/assets/background/login.webp");

const gaiaLogoSource =
  process.env.NODE_ENV === "test"
    ? { uri: "gaia-logo" }
    : require("@shared/assets/logo/logo.webp");

export default function LoginScreen() {
  const router = useRouter();
  const { refreshAuth } = useAuth();
  const [isLoading, setIsLoading] = useState(false);
  const { spacing, fontSize, moderateScale, width } = useResponsive();

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

  // Card max width adapts to screen size
  const cardMaxWidth = Math.min(width * 0.9, 400);
  const logoSize = moderateScale(48, 0.5);
  const logoContainerSize = moderateScale(72, 0.5);

  return (
    <View style={{ flex: 1, backgroundColor: "#060a14" }}>
      {/* Full Background Image */}
      <Image
        source={loginBackgroundSource}
        style={{ position: "absolute", width: "100%", height: "100%" }}
        resizeMode="cover"
        blurRadius={0.5}
      />

      {/* Dark Overlay */}
      <View
        style={{
          position: "absolute",
          width: "100%",
          height: "100%",
          backgroundColor: "rgba(0,0,0,0.5)",
        }}
      />

      <SafeAreaView style={{ flex: 1 }}>
        <KeyboardAvoidingView
          style={{
            flex: 1,
            justifyContent: "center",
            alignItems: "center",
            paddingHorizontal: spacing.lg,
          }}
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          {/* Login Card */}
          <Card
            variant="secondary"
            className="w-full overflow-hidden rounded-[24px] border border-white/10 bg-[#171920]/95"
            style={{
              maxWidth: cardMaxWidth,
              width: "100%",
            }}
          >
            <Card.Body
              style={{
                paddingHorizontal: spacing.xl,
                paddingVertical: moderateScale(40, 0.5),
              }}
            >
              {/* Logo and Title */}
              <View style={{ alignItems: "center", marginBottom: spacing.xl }}>
                <View
                  style={{
                    width: logoContainerSize,
                    height: logoContainerSize,
                    borderRadius: logoContainerSize / 2,
                    backgroundColor: "rgba(0,187,255,0.15)",
                    alignItems: "center",
                    justifyContent: "center",
                    marginBottom: spacing.md,
                  }}
                >
                  <Image
                    source={gaiaLogoSource}
                    style={{ width: logoSize, height: logoSize }}
                    resizeMode="contain"
                  />
                </View>
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
                {/* Login Button */}
                <Button
                  size="lg"
                  className="bg-accent"
                  isDisabled={isLoading}
                  onPress={handleLogin}
                >
                  {isLoading ? (
                    <Spinner color="#000000" size="sm" />
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
                  <PressableFeedback
                    onPress={handleSignUp}
                    isDisabled={isLoading}
                  >
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
            </Card.Body>
          </Card>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
