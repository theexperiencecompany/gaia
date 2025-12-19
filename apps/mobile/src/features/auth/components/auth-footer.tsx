import { View } from "react-native";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";

interface AuthFooterProps {
  showSignUpDisclaimer?: boolean;
}

export function AuthFooter({ showSignUpDisclaimer = false }: AuthFooterProps) {
  const handleTermsPress = () => {
    console.log("Navigate to Terms of Service");
    // TODO: Implement navigation
  };

  const handlePrivacyPress = () => {
    console.log("Navigate to Privacy Policy");
    // TODO: Implement navigation
  };

  return (
    <View className="items-center justify-center mt-6">
      {showSignUpDisclaimer && (
        <Text className="text-sm text-zinc-400 text-center">
          By creating an account, you agree to the{" "}
        </Text>
      )}
      <View className="flex-row flex-wrap justify-center">
        <Button
          variant="link"
          size="sm"
          onPress={handleTermsPress}
          className="p-0 h-auto"
        >
          <Text className="text-sm text-zinc-400 underline">
            Terms of Service
          </Text>
        </Button>
        <Text className="text-sm text-zinc-400 mx-1"> and </Text>
        <Button
          variant="link"
          size="sm"
          onPress={handlePrivacyPress}
          className="p-0 h-auto"
        >
          <Text className="text-sm text-zinc-400 underline">
            Privacy Policy
          </Text>
        </Button>
      </View>
    </View>
  );
}
