import { useQueryClient } from "@tanstack/react-query";
import { PressableFeedback } from "heroui-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActionSheetIOS,
  Alert,
  Platform,
  TextInput,
  View,
} from "react-native";
import {
  BubbleChatAddIcon,
  Cancel01Icon,
  HugeiconsIcon,
  Menu01Icon,
  MoreVerticalIcon,
  Search01Icon,
  Tick01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { Conversation } from "@/features/chat/types";
import { impactHaptic } from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import { useChatStore } from "@/stores/chat-store";
import { chatApi } from "../../api/chat-api";
import { chatKeys, useConversationsQuery } from "../../api/queries";

const TITLE_MAX_LENGTH = 200;

interface ChatHeaderProps {
  onMenuPress: () => void;
  onNewChatPress: () => void;
  onSearchPress?: () => void;
}

export function ChatHeader({
  onMenuPress,
  onNewChatPress,
  onSearchPress,
}: ChatHeaderProps) {
  const { spacing, iconSize, moderateScale, fontSize } = useResponsive();
  const queryClient = useQueryClient();

  const activeChatId = useChatStore((state) => state.activeChatId);
  const { data: conversations } = useConversationsQuery();

  const activeConversation =
    activeChatId && conversations
      ? (conversations.find((c) => c.id === activeChatId) ?? null)
      : null;

  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    if (!isEditing) return;
    const timer = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(timer);
  }, [isEditing]);

  useEffect(() => {
    setIsEditing(false);
  }, [activeChatId]);

  const startEditing = useCallback(() => {
    if (!activeConversation) return;
    impactHaptic("light");
    setEditTitle(activeConversation.title);
    setIsEditing(true);
  }, [activeConversation]);

  const cancelEditing = useCallback(() => {
    setIsEditing(false);
    setEditTitle("");
  }, []);

  const commitRename = useCallback(async () => {
    if (!activeConversation) return;
    const trimmed = editTitle.trim();
    if (!trimmed || trimmed.length === 0 || trimmed.length > TITLE_MAX_LENGTH) {
      cancelEditing();
      return;
    }
    if (trimmed === activeConversation.title) {
      cancelEditing();
      return;
    }

    setIsEditing(false);

    queryClient.setQueryData<Conversation[]>(
      chatKeys.conversations(),
      (prev) => {
        if (!prev) return prev;
        return prev.map((c) =>
          c.id === activeConversation.id ? { ...c, title: trimmed } : c,
        );
      },
    );
    useChatStore.getState().updateConversationTitle(activeConversation.id, trimmed);

    const success = await chatApi.renameConversation(
      activeConversation.id,
      trimmed,
    );
    if (!success) {
      queryClient.setQueryData<Conversation[]>(
        chatKeys.conversations(),
        (prev) => {
          if (!prev) return prev;
          return prev.map((c) =>
            c.id === activeConversation.id
              ? { ...c, title: activeConversation.title }
              : c,
          );
        },
      );
      useChatStore
        .getState()
        .updateConversationTitle(activeConversation.id, activeConversation.title);
    }
  }, [activeConversation, editTitle, cancelEditing, queryClient]);

  const handleOptionsMenu = useCallback(() => {
    if (!activeConversation) return;

    if (Platform.OS === "ios") {
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options: ["Rename", "Cancel"],
          cancelButtonIndex: 1,
        },
        (buttonIndex) => {
          if (buttonIndex === 0) startEditing();
        },
      );
    } else {
      Alert.alert(activeConversation.title, undefined, [
        { text: "Rename", onPress: startEditing },
        { text: "Cancel", style: "cancel" },
      ]);
    }
  }, [activeConversation, startEditing]);

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: spacing.lg,
        paddingVertical: spacing.md,
        backgroundColor: "transparent",
      }}
    >
      {isEditing ? (
        <PressableFeedback onPress={cancelEditing}>
          <View style={{ padding: moderateScale(4, 0.5) }}>
            <HugeiconsIcon
              icon={Cancel01Icon}
              size={iconSize.lg}
              color="#8e8e93"
            />
          </View>
        </PressableFeedback>
      ) : (
        <PressableFeedback onPress={onMenuPress}>
          <View style={{ padding: moderateScale(4, 0.5) }}>
            <HugeiconsIcon
              icon={Menu01Icon}
              size={iconSize.lg}
              color="#ffffff"
            />
          </View>
        </PressableFeedback>
      )}

      <View style={{ flex: 1, alignItems: "center", paddingHorizontal: spacing.sm }}>
        {isEditing ? (
          <TextInput
            ref={inputRef}
            value={editTitle}
            onChangeText={(text) => {
              if (text.length <= TITLE_MAX_LENGTH) setEditTitle(text);
            }}
            onSubmitEditing={commitRename}
            returnKeyType="done"
            selectTextOnFocus
            style={{
              color: "#ffffff",
              fontSize: fontSize.md,
              fontWeight: "600",
              textAlign: "center",
              width: "100%",
              paddingVertical: moderateScale(2, 0.5),
              borderBottomWidth: 1,
              borderBottomColor: "#16c1ff",
            }}
          />
        ) : activeConversation ? (
          <PressableFeedback onPress={startEditing}>
            <Text
              numberOfLines={1}
              style={{
                color: "#ffffff",
                fontSize: fontSize.md,
                fontWeight: "600",
                textAlign: "center",
              }}
            >
              {activeConversation.title}
            </Text>
          </PressableFeedback>
        ) : null}
      </View>

      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        {isEditing ? (
          <PressableFeedback onPress={commitRename}>
            <View style={{ padding: moderateScale(4, 0.5) }}>
              <HugeiconsIcon
                icon={Tick01Icon}
                size={iconSize.md - 2}
                color="#16c1ff"
              />
            </View>
          </PressableFeedback>
        ) : (
          <>
            {onSearchPress && (
              <PressableFeedback onPress={onSearchPress}>
                <View style={{ padding: moderateScale(4, 0.5) }}>
                  <HugeiconsIcon
                    icon={Search01Icon}
                    size={iconSize.md - 2}
                    color="#bbbbbb"
                  />
                </View>
              </PressableFeedback>
            )}
            {activeConversation && (
              <PressableFeedback onPress={handleOptionsMenu}>
                <View style={{ padding: moderateScale(4, 0.5) }}>
                  <HugeiconsIcon
                    icon={MoreVerticalIcon}
                    size={iconSize.md - 2}
                    color="#bbbbbb"
                  />
                </View>
              </PressableFeedback>
            )}
            <PressableFeedback onPress={onNewChatPress}>
              <View style={{ padding: moderateScale(4, 0.5) }}>
                <HugeiconsIcon
                  icon={BubbleChatAddIcon}
                  size={iconSize.md - 2}
                  color="#bbbbbb"
                />
              </View>
            </PressableFeedback>
          </>
        )}
      </View>
    </View>
  );
}
