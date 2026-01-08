import { useRouter } from "expo-router";
import { Button, PressableFeedback } from "heroui-native";
import {
  Image,
  KeyboardAvoidingView,
  Platform,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

export default function SignUpScreen() {
  const router = useRouter();

  const handleGoogleSignUp = () => {
    router.replace("/");
  };

  const handleSignIn = () => {
    router.push("/login");
  };

  return (
    <View className="flex-1 bg-background">
      {/* Full Background Image */}
      <Image
        source={require("@/assets/background/signup.webp")}
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
          {/* Sign Up Card */}
          <View className="w-full max-w-md bg-surface/95 rounded-3xl px-8 py-10 border border-border/20">
            {/* Logo and Title */}
            <View className="items-center mb-8">
              <View className="w-18 h-18 rounded-full bg-accent/15 items-center justify-center mb-4">
                <Image
                  source={require("@/assets/logo/logo.webp")}
                  className="w-12 h-12"
                  resizeMode="contain"
                />
              </View>
              <Text className="text-2xl font-bold text-foreground text-center">
                Time to Supercharge You.
              </Text>
            </View>

            {/* Sign Up Form */}
            <View className="w-full">
              {/* Google Button */}
              <Button size="lg" variant="ghost" onPress={handleGoogleSignUp}>
                <Image
                  source={require("@/assets/icons/google-logo.png")}
                  className="w-5 h-5 mr-2"
                  resizeMode="contain"
                />
                <Button.Label>Continue with Google</Button.Label>
              </Button>

              {/* Sign In Link */}
              <View className="flex-row items-center justify-center mt-4">
                <Text className="text-base text-muted-foreground">
                  Already have an account?{" "}
                </Text>
                <PressableFeedback onPress={handleSignIn}>
                  <Text className="text-base text-accent font-semibold">
                    Sign in
                  </Text>
                </PressableFeedback>
              </View>
            </View>

            {/* Footer */}
            <View className="items-center mt-6">
              <Text className="text-sm text-muted-foreground text-center">
                By creating an account, you agree to the
              </Text>
              <View className="flex-row flex-wrap justify-center">
                <PressableFeedback>
                  <Text className="text-sm text-muted-foreground underline">
                    Terms of Service
                  </Text>
                </PressableFeedback>
                <Text className="text-sm text-muted-foreground mx-1">
                  {" "}
                  and{" "}
                </Text>
                <PressableFeedback>
                  <Text className="text-sm text-muted-foreground underline">
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
