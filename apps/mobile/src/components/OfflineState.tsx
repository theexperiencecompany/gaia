import { GlobeIcon, RepeatIcon } from "@icons";
import { Pressable, Text, View } from "react-native";
import { AppIcon } from "@/components/icons";

interface OfflineStateProps {
  onRetry?: () => void;
}

export function OfflineState({ onRetry }: OfflineStateProps) {
  return (
    <View className="flex-1 items-center justify-center p-6 bg-background">
      <View className="w-16 h-16 rounded-full bg-gray-500/10 items-center justify-center mb-4">
        <AppIcon icon={GlobeIcon} size={32} color="#6b7280" />
      </View>
      <Text className="text-white text-lg font-semibold mb-2 text-center">
        You're Offline
      </Text>
      <Text className="text-gray-400 text-center text-sm leading-5 mb-6 max-w-xs">
        No internet connection detected. Please check your network settings and
        try again.
      </Text>
      {onRetry ? (
        <Pressable
          onPress={onRetry}
          className="flex-row items-center gap-2 bg-primary px-6 py-3 rounded-lg"
        >
          <AppIcon icon={RepeatIcon} size={16} color="#ffffff" />
          <Text className="text-white font-medium">Try Again</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
