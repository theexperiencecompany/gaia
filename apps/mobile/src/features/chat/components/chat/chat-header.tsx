import { PressableFeedback } from "heroui-native";
import { useCallback, useState } from "react";
import { Alert, Modal, Pressable, TextInput, View } from "react-native";
import {
  AiChipIcon,
  AppIcon,
  ArrowDownIcon,
  BubbleChatAddIcon,
  Delete02Icon,
  FavouriteIcon,
  Menu01Icon,
  PencilEdit02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import {
  useCurrentModel,
  useModels,
  useSelectModel,
} from "../../hooks/use-models";

interface ChatHeaderProps {
  onMenuPress: () => void;
  onNewChatPress: () => void;
  conversationTitle?: string;
  isStarred?: boolean;
  onStarPress?: () => void;
  onRenamePress?: (newTitle: string) => void;
  onDeletePress?: () => void;
}

export function ChatHeader({
  onMenuPress,
  onNewChatPress,
  conversationTitle,
  isStarred = false,
  onStarPress,
  onRenamePress,
  onDeletePress,
}: ChatHeaderProps) {
  const { spacing, iconSize, moderateScale, fontSize } = useResponsive();

  const [optionsVisible, setOptionsVisible] = useState(false);
  const [modelPickerVisible, setModelPickerVisible] = useState(false);
  const [renameVisible, setRenameVisible] = useState(false);
  const [renameValue, setRenameValue] = useState("");

  const hasConversation = !!conversationTitle;

  const { data: models } = useModels();
  const currentModel = useCurrentModel();
  const { select: selectModel, isPending: isSelectingModel } = useSelectModel();

  const handleRenameSubmit = useCallback(() => {
    if (renameValue.trim()) {
      onRenamePress?.(renameValue.trim());
    }
    setRenameVisible(false);
    setRenameValue("");
  }, [renameValue, onRenamePress]);

  const handleDelete = useCallback(() => {
    setOptionsVisible(false);
    Alert.alert(
      "Delete Conversation",
      "Are you sure you want to delete this conversation?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => onDeletePress?.(),
        },
      ],
    );
  }, [onDeletePress]);

  const iconButtonStyle = {
    padding: moderateScale(6, 0.5),
    borderRadius: moderateScale(10, 0.5),
    backgroundColor: "rgba(255,255,255,0.06)",
  };

  const groupedModels: Record<string, typeof models> = {};
  if (models) {
    for (const model of models) {
      const provider = model.model_provider ?? "Other";
      if (!groupedModels[provider]) groupedModels[provider] = [];
      groupedModels[provider]?.push(model);
    }
  }

  return (
    <>
      {/* Header bar */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
          backgroundColor: "#131416",
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.1)",
          minHeight: moderateScale(52, 0.5),
        }}
      >
        {/* Left: hamburger menu */}
        <PressableFeedback onPress={onMenuPress}>
          <View style={iconButtonStyle}>
            <AppIcon icon={Menu01Icon} size={iconSize.md} color="#ffffff" />
          </View>
        </PressableFeedback>

        {/* Center: title + model selector */}
        <View
          style={{
            flex: 1,
            marginHorizontal: spacing.sm,
            alignItems: "center",
            gap: 2,
          }}
        >
          <Text
            numberOfLines={1}
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "rgba(255,255,255,0.92)",
              textAlign: "center",
            }}
          >
            {conversationTitle ?? "New Chat"}
          </Text>

          {/* Model selector pill */}
          <Pressable
            onPress={() => setModelPickerVisible(true)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              paddingHorizontal: moderateScale(8, 0.5),
              paddingVertical: 2,
              borderRadius: 999,
              backgroundColor: "rgba(255,255,255,0.06)",
            }}
          >
            <AppIcon
              icon={AiChipIcon}
              size={moderateScale(11, 0.5)}
              color="#8e8e93"
            />
            <Text
              numberOfLines={1}
              style={{
                fontSize: fontSize.xs - 1,
                color: "#8e8e93",
                maxWidth: moderateScale(120, 0.5),
              }}
            >
              {currentModel?.name ?? "Select model"}
            </Text>
            <AppIcon
              icon={ArrowDownIcon}
              size={moderateScale(10, 0.5)}
              color="#8e8e93"
            />
          </Pressable>
        </View>

        {/* Right: new chat or conversation options */}
        <View style={{ flexDirection: "row" }}>
          {hasConversation ? (
            <PressableFeedback onPress={() => setOptionsVisible(true)}>
              <View style={iconButtonStyle}>
                <AppIcon
                  icon={PencilEdit02Icon}
                  size={iconSize.md}
                  color="#bbbbbb"
                />
              </View>
            </PressableFeedback>
          ) : (
            <PressableFeedback onPress={onNewChatPress}>
              <View style={iconButtonStyle}>
                <AppIcon
                  icon={BubbleChatAddIcon}
                  size={iconSize.md}
                  color="#bbbbbb"
                />
              </View>
            </PressableFeedback>
          )}
        </View>
      </View>

      {/* Model Picker Bottom Sheet */}
      <Modal
        visible={modelPickerVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setModelPickerVisible(false)}
      >
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.6)" }}
          onPress={() => setModelPickerVisible(false)}
        >
          <Pressable
            style={{
              position: "absolute",
              bottom: 0,
              left: 0,
              right: 0,
              backgroundColor: "#1a1a1c",
              borderTopLeftRadius: moderateScale(20, 0.5),
              borderTopRightRadius: moderateScale(20, 0.5),
              borderTopWidth: 1,
              borderColor: "rgba(255,255,255,0.1)",
              paddingBottom: spacing.xl,
              maxHeight: "80%",
            }}
          >
            {/* Drag handle */}
            <View
              style={{
                alignItems: "center",
                paddingTop: spacing.sm,
                paddingBottom: spacing.md,
              }}
            >
              <View
                style={{
                  width: moderateScale(36, 0.5),
                  height: 4,
                  borderRadius: 2,
                  backgroundColor: "rgba(255,255,255,0.2)",
                }}
              />
            </View>

            <View
              style={{
                paddingHorizontal: spacing.md,
                marginBottom: spacing.sm,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.base,
                  fontWeight: "600",
                  color: "#ffffff",
                }}
              >
                Select Model
              </Text>
            </View>

            {models && models.length > 0
              ? Object.entries(groupedModels).map(
                  ([provider, providerModels]) => (
                    <View key={provider}>
                      <Text
                        style={{
                          fontSize: fontSize.xs,
                          color: "#8e8e93",
                          textTransform: "uppercase",
                          letterSpacing: 0.8,
                          paddingHorizontal: spacing.md,
                          paddingTop: spacing.sm,
                          paddingBottom: spacing.xs,
                        }}
                      >
                        {provider}
                      </Text>
                      {providerModels?.map((model) => {
                        const isSelected =
                          currentModel?.model_id === model.model_id;
                        const isFree =
                          model.lowest_tier.toLowerCase() === "free";

                        return (
                          <Pressable
                            key={model.model_id}
                            onPress={() => {
                              if (!isSelectingModel) {
                                selectModel(model.model_id);
                                setModelPickerVisible(false);
                              }
                            }}
                            style={{
                              flexDirection: "row",
                              alignItems: "center",
                              paddingHorizontal: spacing.md,
                              paddingVertical: spacing.sm,
                              backgroundColor: isSelected
                                ? "rgba(0,187,255,0.08)"
                                : "transparent",
                              gap: spacing.sm,
                            }}
                          >
                            <View style={{ flex: 1 }}>
                              <View
                                style={{
                                  flexDirection: "row",
                                  alignItems: "center",
                                  gap: spacing.xs,
                                  flexWrap: "wrap",
                                }}
                              >
                                <Text
                                  style={{
                                    fontSize: fontSize.sm,
                                    fontWeight: isSelected ? "600" : "400",
                                    color: isSelected ? "#00bbff" : "#ffffff",
                                  }}
                                >
                                  {model.name}
                                </Text>
                                {!isFree && (
                                  <View
                                    style={{
                                      paddingHorizontal: moderateScale(6, 0.5),
                                      paddingVertical: 1,
                                      borderRadius: 4,
                                      backgroundColor: "rgba(255,179,0,0.15)",
                                    }}
                                  >
                                    <Text
                                      style={{
                                        fontSize: fontSize.xs - 1,
                                        color: "#ffb300",
                                        fontWeight: "600",
                                      }}
                                    >
                                      Pro
                                    </Text>
                                  </View>
                                )}
                                {model.is_default && (
                                  <View
                                    style={{
                                      paddingHorizontal: moderateScale(6, 0.5),
                                      paddingVertical: 1,
                                      borderRadius: 4,
                                      backgroundColor: "rgba(52,199,89,0.15)",
                                    }}
                                  >
                                    <Text
                                      style={{
                                        fontSize: fontSize.xs - 1,
                                        color: "#34c759",
                                        fontWeight: "600",
                                      }}
                                    >
                                      Default
                                    </Text>
                                  </View>
                                )}
                              </View>
                              {model.description && (
                                <Text
                                  numberOfLines={1}
                                  style={{
                                    fontSize: fontSize.xs,
                                    color: "#8e8e93",
                                    marginTop: 2,
                                  }}
                                >
                                  {model.description}
                                </Text>
                              )}
                            </View>

                            {isSelected && (
                              <View
                                style={{
                                  width: moderateScale(8, 0.5),
                                  height: moderateScale(8, 0.5),
                                  borderRadius: 999,
                                  backgroundColor: "#00bbff",
                                }}
                              />
                            )}
                          </Pressable>
                        );
                      })}
                    </View>
                  ),
                )
              : null}
          </Pressable>
        </Pressable>
      </Modal>

      {/* Conversation Options Dropdown */}
      <Modal
        visible={optionsVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setOptionsVisible(false)}
      >
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.5)" }}
          onPress={() => setOptionsVisible(false)}
        >
          <View
            style={{
              position: "absolute",
              top: moderateScale(72, 0.5),
              right: spacing.md,
              backgroundColor: "#1e1e20",
              borderRadius: moderateScale(12, 0.5),
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.1)",
              minWidth: moderateScale(180, 0.5),
              overflow: "hidden",
            }}
          >
            <Pressable
              onPress={() => {
                setOptionsVisible(false);
                onStarPress?.();
              }}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.sm,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm,
              }}
            >
              <AppIcon
                icon={FavouriteIcon}
                size={iconSize.md}
                color={isStarred ? "#f5a623" : "#8e8e93"}
              />
              <Text style={{ fontSize: fontSize.sm, color: "#ffffff" }}>
                {isStarred ? "Unstar" : "Star"}
              </Text>
            </Pressable>

            <View
              style={{ height: 1, backgroundColor: "rgba(255,255,255,0.08)" }}
            />

            <Pressable
              onPress={() => {
                setOptionsVisible(false);
                setRenameValue(conversationTitle ?? "");
                setRenameVisible(true);
              }}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.sm,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm,
              }}
            >
              <AppIcon
                icon={PencilEdit02Icon}
                size={iconSize.md}
                color="#8e8e93"
              />
              <Text style={{ fontSize: fontSize.sm, color: "#ffffff" }}>
                Rename
              </Text>
            </Pressable>

            <View
              style={{ height: 1, backgroundColor: "rgba(255,255,255,0.08)" }}
            />

            <Pressable
              onPress={handleDelete}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.sm,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm,
              }}
            >
              <AppIcon icon={Delete02Icon} size={iconSize.md} color="#ff453a" />
              <Text style={{ fontSize: fontSize.sm, color: "#ff453a" }}>
                Delete
              </Text>
            </Pressable>
          </View>
        </Pressable>
      </Modal>

      {/* Rename Modal */}
      <Modal
        visible={renameVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setRenameVisible(false)}
      >
        <Pressable
          style={{
            flex: 1,
            backgroundColor: "rgba(0,0,0,0.5)",
            justifyContent: "center",
            alignItems: "center",
          }}
          onPress={() => setRenameVisible(false)}
        >
          <Pressable
            style={{
              backgroundColor: "#1e1e20",
              borderRadius: moderateScale(16, 0.5),
              borderWidth: 1,
              borderColor: "rgba(255,255,255,0.1)",
              padding: spacing.lg,
              width: "80%",
              maxWidth: 320,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.base,
                fontWeight: "600",
                color: "#ffffff",
                marginBottom: spacing.sm,
              }}
            >
              Rename Conversation
            </Text>
            <TextInput
              value={renameValue}
              onChangeText={setRenameValue}
              placeholder="Enter new title"
              placeholderTextColor="rgba(255,255,255,0.3)"
              autoFocus
              onSubmitEditing={handleRenameSubmit}
              style={{
                backgroundColor: "rgba(255,255,255,0.06)",
                borderRadius: moderateScale(8, 0.5),
                paddingHorizontal: spacing.sm,
                paddingVertical: spacing.sm,
                fontSize: fontSize.sm,
                color: "#ffffff",
                marginBottom: spacing.md,
              }}
            />
            <View
              style={{
                flexDirection: "row",
                justifyContent: "flex-end",
                gap: spacing.sm,
              }}
            >
              <Pressable
                onPress={() => setRenameVisible(false)}
                style={{
                  paddingHorizontal: spacing.sm,
                  paddingVertical: spacing.xs,
                  borderRadius: moderateScale(8, 0.5),
                }}
              >
                <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
                  Cancel
                </Text>
              </Pressable>
              <Pressable
                onPress={handleRenameSubmit}
                style={{
                  paddingHorizontal: spacing.sm,
                  paddingVertical: spacing.xs,
                  borderRadius: moderateScale(8, 0.5),
                  backgroundColor: "#00bbff",
                }}
              >
                <Text style={{ fontSize: fontSize.sm, color: "#000000" }}>
                  Save
                </Text>
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}
