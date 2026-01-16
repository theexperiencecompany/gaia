import { PressableFeedback } from "heroui-native";
import { Text, View } from "react-native";

interface AuthFooterProps {
  showSignUpDisclaimer?: boolean;
}

export function AuthFooter({ showSignUpDisclaimer = false }: AuthFooterProps) {
  const handleTermsPress = () => {};

  const handlePrivacyPress = () => {};

  return (
    <View className="items-center justify-center mt-6">
      {showSignUpDisclaimer && (
        <Text className="text-sm text-zinc-400 text-center">
          By creating an account, you agree to the{" "}
        </Text>
      )}
      <View className="flex-row flex-wrap justify-center">
        <PressableFeedback onPress={handleTermsPress}>
          <Text className="text-sm text-zinc-400 underline">
            Terms of Service
          </Text>
        </PressableFeedback>
        <Text className="text-sm text-zinc-400 mx-1"> and </Text>
        <PressableFeedback onPress={handlePrivacyPress}>
          <Text className="text-sm text-zinc-400 underline">
            Privacy Policy
          </Text>
        </PressableFeedback>
      </View>
    </View>
  );
}
