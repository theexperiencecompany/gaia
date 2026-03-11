import { useQueryClient } from "@tanstack/react-query";
import { Popover, PressableFeedback, TextField } from "heroui-native";
import { useCallback, useEffect, useRef, useState } from "react";
import { type TextInput, View } from "react-native";
import {
  BubbleChatAddIcon,
  Cancel01Icon,
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
  const [isMenuOpen, setIsMenuOpen] = useState(false);
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
    setIsMenuOpen(false);
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
    useChatStore
      .getState()
      .updateConversationTitle(activeConversation.id, trimmed);

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
        .updateConversationTitle(
          activeConversation.id,
          activeConversation.title,
        );
    }
  }, [activeConversation, editTitle, cancelEditing, queryClient]);

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
            <Cancel01Icon size={iconSize.lg} color="#8e8e93" />
          </View>
        </PressableFeedback>
      ) : (
        <PressableFeedback onPress={onMenuPress}>
          <View style={{ padding: moderateScale(4, 0.5) }}>
            <Menu01Icon size={iconSize.lg} color="#ffffff" />
          </View>
        </PressableFeedback>
      )}

      <View
        style={{ flex: 1, alignItems: "center", paddingHorizontal: spacing.sm }}
      >
        {isEditing ? (
          <TextField className="w-full">
            <TextField.Input
              ref={inputRef}
              value={editTitle}
              onChangeText={(text) => {
                if (text.length <= TITLE_MAX_LENGTH) setEditTitle(text);
              }}
              onSubmitEditing={commitRename}
              returnKeyType="done"
              selectTextOnFocus
              className="w-full"
              style={{
                color: "#ffffff",
                fontSize: fontSize.md,
                fontWeight: "600",
                textAlign: "center",
                borderBottomWidth: 1,
                borderBottomColor: "#16c1ff",
              }}
            />
          </TextField>
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
              <Tick01Icon size={iconSize.md - 2} color="#16c1ff" />
            </View>
          </PressableFeedback>
        ) : (
          <>
            {onSearchPress && (
              <PressableFeedback onPress={onSearchPress}>
                <View style={{ padding: moderateScale(4, 0.5) }}>
                  <Search01Icon size={iconSize.md - 2} color="#bbbbbb" />
                </View>
              </PressableFeedback>
            )}
            {activeConversation && (
              <Popover isOpen={isMenuOpen} onOpenChange={setIsMenuOpen}>
                <Popover.Trigger>
                  <View style={{ padding: moderateScale(4, 0.5) }}>
                    <MoreVerticalIcon size={iconSize.md - 2} color="#bbbbbb" />
                  </View>
                </Popover.Trigger>
                <Popover.Portal>
                  <Popover.Overlay onPress={() => setIsMenuOpen(false)} />
                  <Popover.Content placement="bottom" align="end">
                    <PressableFeedback onPress={startEditing}>
                      <View
                        style={{
                          paddingHorizontal: spacing.lg,
                          paddingVertical: spacing.md,
                        }}
                      >
                        <Text
                          style={{
                            color: "#ffffff",
                            fontSize: fontSize.sm,
                          }}
                        >
                          Rename
                        </Text>
                      </View>
                    </PressableFeedback>
                  </Popover.Content>
                </Popover.Portal>
              </Popover>
            )}
            <PressableFeedback onPress={onNewChatPress}>
              <View style={{ padding: moderateScale(4, 0.5) }}>
                <BubbleChatAddIcon size={iconSize.md - 2} color="#bbbbbb" />
              </View>
            </PressableFeedback>
          </>
        )}
      </View>
    </View>
  );
}
