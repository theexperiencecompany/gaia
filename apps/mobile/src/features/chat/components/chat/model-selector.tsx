import {
  Image,
  Modal,
  ScrollView,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import {
  Cancel01Icon,
  CheckmarkCircle01Icon,
  HugeiconsIcon,
} from "@/components/icons";
import type { AIModel } from "../../types";

interface ModelSelectorProps {
  visible: boolean;
  selectedModel: AIModel;
  models: AIModel[];
  onSelect: (model: AIModel) => void;
  onClose: () => void;
}

export function ModelSelector({
  visible,
  selectedModel,
  models,
  onSelect,
  onClose,
}: ModelSelectorProps) {
  const handleSelect = (model: AIModel) => {
    onSelect(model);
    onClose();
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <TouchableOpacity
        className="flex-1 bg-black/60 justify-center items-center px-6"
        activeOpacity={1}
        onPress={onClose}
      >
        <View className="bg-background rounded-2xl w-full max-w-sm max-h-[70%] shadow-xl elevation-8 overflow-hidden">
          <View className="flex-row items-center justify-between px-5 py-4 border-b border-border">
            <Text className="text-lg font-bold text-foreground">
              Select AI Model
            </Text>
            <TouchableOpacity
              onPress={onClose}
              className="p-1"
              activeOpacity={0.7}
            >
              <HugeiconsIcon icon={Cancel01Icon} size={22} color="#ffffff" />
            </TouchableOpacity>
          </View>

          <ScrollView
            className="max-h-[400px]"
            showsVerticalScrollIndicator={false}
          >
            {models.map((model) => (
              <TouchableOpacity
                key={model.id}
                className={`flex-row items-center justify-between px-5 py-4 border-b border-border transition-colors ${
                  selectedModel.id === model.id ? "bg-secondary/20" : ""
                }`}
                onPress={() => handleSelect(model)}
                activeOpacity={0.7}
              >
                <View className="flex-row items-center gap-3 flex-1">
                  <Image
                    source={{ uri: model.icon }}
                    className="w-8 h-8 rounded-lg"
                    resizeMode="contain"
                  />
                  <View className="flex-1">
                    <View className="flex-row items-center gap-2">
                      <Text className="text-base font-semibold text-foreground">
                        {model.name}
                      </Text>
                      {model.isPro && (
                        <View className="bg-accent px-1.5 py-0.5 rounded-md">
                          <Text className="text-[9px] font-black text-black uppercase tracking-tighter">
                            PRO
                          </Text>
                        </View>
                      )}
                    </View>
                    <Text className="text-xs text-muted-foreground mt-0.5 uppercase tracking-wide font-medium">
                      {model.provider}
                    </Text>
                  </View>
                </View>
                {selectedModel.id === model.id && (
                  <HugeiconsIcon
                    icon={CheckmarkCircle01Icon}
                    size={22}
                    color="#00bbff"
                  />
                )}
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
      </TouchableOpacity>
    </Modal>
  );
}
