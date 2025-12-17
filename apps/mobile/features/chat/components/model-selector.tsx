/**
 * ModelSelector Component
 * Dropdown modal for selecting AI models
 */

import { Ionicons } from "@expo/vector-icons";
import {
  Image,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { ChatTheme } from "@/shared/constants/chat-theme";
import type { AIModel } from "../types";

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
        style={styles.overlay}
        activeOpacity={1}
        onPress={onClose}
      >
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Select AI Model</Text>
            <TouchableOpacity onPress={onClose} style={styles.closeButton}>
              <Ionicons name="close" size={24} color={ChatTheme.textPrimary} />
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.modelList}>
            {models.map((model) => (
              <TouchableOpacity
                key={model.id}
                style={[
                  styles.modelItem,
                  selectedModel.id === model.id && styles.modelItemSelected,
                ]}
                onPress={() => handleSelect(model)}
                activeOpacity={0.7}
              >
                <View style={styles.modelInfo}>
                  <Image
                    source={{ uri: model.icon }}
                    style={styles.modelIcon}
                    resizeMode="contain"
                  />
                  <View style={styles.modelTextContainer}>
                    <View style={styles.modelNameRow}>
                      <Text style={styles.modelName}>{model.name}</Text>
                      {model.isPro && (
                        <View style={styles.proBadge}>
                          <Text style={styles.proText}>PRO</Text>
                        </View>
                      )}
                    </View>
                    <Text style={styles.modelProvider}>{model.provider}</Text>
                  </View>
                </View>
                {selectedModel.id === model.id && (
                  <Ionicons
                    name="checkmark-circle"
                    size={24}
                    color={ChatTheme.accent}
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

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0, 0, 0, 0.5)",
    justifyContent: "center",
    alignItems: "center",
    padding: ChatTheme.spacing.lg,
  },
  modalContent: {
    backgroundColor: ChatTheme.background,
    borderRadius: ChatTheme.borderRadius.lg,
    width: "100%",
    maxWidth: 400,
    maxHeight: "80%",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 8,
  },
  modalHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: ChatTheme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: ChatTheme.border,
  },
  modalTitle: {
    fontSize: ChatTheme.fontSize.lg,
    fontWeight: "600",
    color: ChatTheme.textPrimary,
  },
  closeButton: {
    padding: ChatTheme.spacing.xs,
  },
  modelList: {
    maxHeight: 400,
  },
  modelItem: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: ChatTheme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: ChatTheme.border,
  },
  modelItemSelected: {
    backgroundColor: ChatTheme.messageBackground,
  },
  modelInfo: {
    flexDirection: "row",
    alignItems: "center",
    gap: ChatTheme.spacing.sm,
    flex: 1,
  },
  modelIcon: {
    width: 32,
    height: 32,
    borderRadius: ChatTheme.borderRadius.sm,
  },
  modelTextContainer: {
    flex: 1,
  },
  modelNameRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: ChatTheme.spacing.xs,
  },
  modelName: {
    fontSize: ChatTheme.fontSize.md,
    fontWeight: "500",
    color: ChatTheme.textPrimary,
  },
  modelProvider: {
    fontSize: ChatTheme.fontSize.sm,
    color: ChatTheme.textSecondary,
    marginTop: 2,
  },
  proBadge: {
    backgroundColor: ChatTheme.accent,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: ChatTheme.borderRadius.sm,
  },
  proText: {
    fontSize: 10,
    fontWeight: "700",
    color: "#fff",
    letterSpacing: 0.5,
  },
});
