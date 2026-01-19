import { useRouter } from "expo-router";
import { Button, PressableFeedback } from "heroui-native";
import {
  Image,
  KeyboardAvoidingView,
  Linking,
  Platform,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

export default function SignUpScreen() {
  const router = useRouter();
  const { spacing, fontSize, moderateScale, width } = useResponsive();

  const handleGoogleSignUp = () => {
    router.replace("/");
  };

  const handleSignIn = () => {
    router.push("/login");
  };

  // Card max width adapts to screen size
  const cardMaxWidth = Math.min(width * 0.9, 400);
  const logoSize = moderateScale(48, 0.5);
  const logoContainerSize = moderateScale(72, 0.5);

  return (
    <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
      {/* Full Background Image */}
      <Image
        source={require("@/assets/background/signup.webp")}
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
          {/* Sign Up Card */}
          <View
            style={{
              width: "100%",
              maxWidth: cardMaxWidth,
              backgroundColor: "rgba(28,28,30,0.95)",
              borderRadius: moderateScale(24, 0.5),
              paddingHorizontal: spacing.xl,
              paddingVertical: moderateScale(40, 0.5),
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.1)",
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
                  source={require("@shared/assets/logo/logo.webp")}
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
                Time to Supercharge You.
              </Text>
            </View>

            {/* Sign Up Form */}
            <View style={{ width: "100%" }}>
              {/* Google Button */}
              <Button size="lg" variant="ghost" onPress={handleGoogleSignUp}>
                <Image
                  source={require("@/assets/icons/google-logo.png")}
                  style={{
                    width: moderateScale(20, 0.5),
                    height: moderateScale(20, 0.5),
                    marginRight: spacing.sm,
                  }}
                  resizeMode="contain"
                />
                <Button.Label>Continue with Google</Button.Label>
              </Button>

              {/* Sign In Link */}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "center",
                  marginTop: spacing.md,
                }}
              >
                <Text style={{ fontSize: fontSize.base, color: "#8e8e93" }}>
                  Already have an account?{" "}
                </Text>
                <PressableFeedback onPress={handleSignIn}>
                  <Text
                    style={{
                      fontSize: fontSize.base,
                      color: "#00bbff",
                      fontWeight: "600",
                    }}
                  >
                    Sign in
                  </Text>
                </PressableFeedback>
              </View>
            </View>

            {/* Footer */}
            <View style={{ alignItems: "center", marginTop: spacing.lg }}>
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#8e8e93",
                  textAlign: "center",
                }}
              >
                By creating an account, you agree to the
              </Text>
              <View
                style={{
                  flexDirection: "row",
                  flexWrap: "wrap",
                  justifyContent: "center",
                }}
              >
                <PressableFeedback
                  onPress={() => Linking.openURL("https://heygaia.io/terms")}
                >
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
                <PressableFeedback
                  onPress={() => Linking.openURL("https://heygaia.io/privacy")}
                >
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
            </View>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
