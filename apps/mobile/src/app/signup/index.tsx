import { useRouter } from "expo-router";
import { Button, PressableFeedback } from "heroui-native";
import { Image, Linking, View } from "react-native";
import { Text } from "@/components/ui/text";
import {
  AuthCard,
  AuthLogo,
  AuthScreenLayout,
} from "@/features/auth/components/AuthScreenLayout";
import { useResponsive } from "@/lib/responsive";

export default function SignUpScreen() {
  const router = useRouter();
  const { spacing, fontSize, moderateScale } = useResponsive();

  const handleGoogleSignUp = () => {
    router.replace("/");
  };

  const handleSignIn = () => {
    router.push("/login");
  };

  return (
    <AuthScreenLayout
      backgroundSource={require("@/assets/background/signup.webp")}
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
            Time to Supercharge You.
          </Text>
        </View>

        {/* Sign Up Form */}
        <View style={{ width: "100%" }}>
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
      </AuthCard>
    </AuthScreenLayout>
  );
}
