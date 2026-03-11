import { AlertCircleIcon, RepeatIcon } from "@icons";
import { Pressable, Text, View } from "react-native";
import { AppIcon } from "@/components/icons";

interface NetworkErrorStateProps {
  onRetry?: () => void;
  message?: string;
}

export function NetworkErrorState({
  onRetry,
  message = "Unable to connect to the server. Please check your connection and try again.",
}: NetworkErrorStateProps) {
  return (
    <View className="flex-1 items-center justify-center p-6 bg-background">
      <View className="w-16 h-16 rounded-full bg-red-500/10 items-center justify-center mb-4">
        <AppIcon icon={AlertCircleIcon} size={32} color="#ef4444" />
      </View>
      <Text className="text-white text-lg font-semibold mb-2 text-center">
        Connection Error
      </Text>
      <Text className="text-gray-400 text-center text-sm leading-5 mb-6 max-w-xs">
        {message}
      </Text>
      {onRetry ? (
        <Pressable
          onPress={onRetry}
          className="flex-row items-center gap-2 bg-primary px-6 py-3 rounded-lg"
        >
          <AppIcon icon={RepeatIcon} size={16} color="#ffffff" />
          <Text className="text-white font-medium">Retry</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
