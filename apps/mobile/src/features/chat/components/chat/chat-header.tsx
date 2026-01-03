import { PressableFeedback } from "heroui-native";
import { Text, View } from "react-native";
import {
  ArrowDown01Icon,
  Edit01Icon,
  HugeiconsIcon,
  Menu01Icon,
  Search01Icon,
} from "@/components/icons";
import type { AIModel } from "@/features/chat/types";

interface ChatHeaderProps {
  onMenuPress: () => void;
  onNewChatPress: () => void;
  onSearchPress?: () => void;
  selectedModel?: AIModel;
  onModelChange?: (model: AIModel) => void;
}

export function ChatHeader({
  onMenuPress,
  onNewChatPress,
  onSearchPress,
}: ChatHeaderProps) {
  return (
    <View className="flex-row items-center justify-between px-6 py-4 border-b border-border/10 bg-surface-1">
      <PressableFeedback onPress={onMenuPress}>
        <View className="p-1">
          <HugeiconsIcon icon={Menu01Icon} size={24} color="#ffffff" />
        </View>
      </PressableFeedback>

      <View className="flex-row items-center gap-2 px-3 py-1.5">
        <Text className="text-sm text-foreground font-bold tracking-tight">
          {"GAIA Free"}
        </Text>
        <HugeiconsIcon icon={ArrowDown01Icon} size={14} color="#666666" />
      </View>

      <View className="flex-row gap-1">
        {onSearchPress && (
          <PressableFeedback onPress={onSearchPress}>
            <View className="p-1">
              <HugeiconsIcon icon={Search01Icon} size={20} color="#ffffff" />
            </View>
          </PressableFeedback>
        )}
        <PressableFeedback onPress={onNewChatPress}>
          <View className="p-1">
            <HugeiconsIcon icon={Edit01Icon} size={18} color="#bbbbbb" />
          </View>
        </PressableFeedback>
      </View>
    </View>
  );
}
