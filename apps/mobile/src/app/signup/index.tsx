import { useRouter } from "expo-router";
import { Image, KeyboardAvoidingView, Platform, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";

export default function SignUpScreen() {
  const router = useRouter();

  const handleGoogleSignUp = () => {
    console.log("Google Sign Up");
    // TODO: Implement Google sign up
    router.replace("/");
  };

  const handleSignIn = () => {
    router.push("/login");
  };

  return (
    <View className="flex-1 bg-[#0c1f3d]">
      {/* Full Background Image */}
      <Image
        source={require("@/assets/background/signup.webp")}
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
          {/* Sign Up Card */}
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
                Time to Supercharge You.
              </Text>
            </View>

            {/* Sign Up Form */}
            <View className="w-full">
              {/* Google Button */}
              <Button
                variant="secondary"
                size="lg"
                className="bg-zinc-800/80 rounded-xl mb-4 flex-row items-center justify-center gap-2 border border-white/20"
                onPress={handleGoogleSignUp}
              >
                <Image
                  source={require("@/assets/icons/google-logo.png")}
                  className="w-[18px] h-[18px]"
                  resizeMode="contain"
                />
                <Text className="text-base font-medium text-white">
                  Continue with Google
                </Text>
              </Button>

              {/* Sign In Link */}
              <View className="flex-row items-center justify-center mt-4">
                <Text className="text-base text-zinc-400">
                  Already have an account?{" "}
                </Text>
                <Button
                  variant="link"
                  size="sm"
                  onPress={handleSignIn}
                  className="p-0 h-auto"
                >
                  <Text className="text-base text-[#16c1ff] font-semibold">
                    Sign in
                  </Text>
                </Button>
              </View>
            </View>

            {/* Footer */}
            <View className="items-center justify-center mt-6">
              <Text className="text-sm text-zinc-400 text-center">
                By creating an account, you agree to the{" "}
              </Text>
              <View className="flex-row flex-wrap justify-center">
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
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
