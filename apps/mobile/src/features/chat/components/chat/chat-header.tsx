import { useState } from "react";
import { Text, TouchableOpacity, View } from "react-native";
import {
  ArrowDown01Icon,
  Edit01Icon,
  HugeiconsIcon,
  Menu01Icon,
  Search01Icon,
} from "@/components/icons";
import { AI_MODELS, DEFAULT_MODEL } from "@/features/chat/data/models";
import type { AIModel } from "@/features/chat/types";
import { ModelSelector } from "./model-selector";

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
  selectedModel = DEFAULT_MODEL,
  onModelChange,
}: ChatHeaderProps) {
  const [isModelSelectorVisible, setIsModelSelectorVisible] = useState(false);

  const handleModelSelect = (model: AIModel) => {
    onModelChange?.(model);
  };

  return (
    <View className="flex-row items-center justify-between px-6 py-4 border-b border-border/10 bg-surface-1">
      <TouchableOpacity
        onPress={onMenuPress}
        className="p-1"
        activeOpacity={0.7}
      >
        <HugeiconsIcon icon={Menu01Icon} size={24} color="#ffffff" />
      </TouchableOpacity>

      <TouchableOpacity
        className="flex-row items-center gap-2 px-3 py-1.5"
        activeOpacity={0.7}
        onPress={() => setIsModelSelectorVisible(true)}
      >
        <Text className="text-sm text-foreground font-bold tracking-tight">
          {selectedModel.name}
        </Text>
        <HugeiconsIcon icon={ArrowDown01Icon} size={14} color="#666666" />
      </TouchableOpacity>

      <ModelSelector
        visible={isModelSelectorVisible}
        selectedModel={selectedModel}
        models={AI_MODELS}
        onSelect={handleModelSelect}
        onClose={() => setIsModelSelectorVisible(false)}
      />

      <View className="flex-row gap-1">
        {onSearchPress && (
          <TouchableOpacity
            className="p-1"
            activeOpacity={0.7}
            onPress={onSearchPress}
          >
            <HugeiconsIcon icon={Search01Icon} size={20} color="#ffffff" />
          </TouchableOpacity>
        )}
        <TouchableOpacity
          className="p-1"
          onPress={onNewChatPress}
          activeOpacity={0.7}
        >
          <HugeiconsIcon icon={Edit01Icon} size={18} color="#bbbbbb" />
        </TouchableOpacity>
      </View>
    </View>
  );
}
