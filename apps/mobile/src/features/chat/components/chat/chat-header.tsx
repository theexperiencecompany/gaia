import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import Animated, { ZoomIn } from "react-native-reanimated";
import {
  Cancel01Icon,
  Menu01Icon,
  Notification01Icon,
  PencilEdit02Icon,
  Tick01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { Conversation } from "@/features/chat/types";
import { useInappNotifications } from "@/features/notifications/hooks/use-inapp-notifications";
import { impactHaptic } from "@/lib/haptics";
import { useResponsive } from "@/lib/responsive";
import { useChatStore } from "@/stores/chat-store";
import { chatApi } from "../../api/chat-api";
import { chatKeys, useConversationsQuery } from "../../api/queries";

const TITLE_MAX_LENGTH = 200;

interface ChatHeaderProps {
  onMenuPress: () => void;
  onNewChatPress: () => void;
}

export function ChatHeader({ onMenuPress, onNewChatPress }: ChatHeaderProps) {
  const { spacing, iconSize, moderateScale, fontSize } = useResponsive();
  const queryClient = useQueryClient();
  const router = useRouter();
  const { unreadNotifications } = useInappNotifications();
  const hasUnread = unreadNotifications.length > 0;

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
        paddingHorizontal: spacing.sm,
        paddingVertical: spacing.sm,
        backgroundColor: "transparent",
      }}
    >
      {isEditing ? (
        <Pressable onPress={cancelEditing}>
          <View style={{ padding: moderateScale(4, 0.5) }}>
            <Cancel01Icon size={iconSize.md} color="#a1a1aa" />
          </View>
        </Pressable>
      ) : (
        <Pressable
          onPress={() => {
            impactHaptic("light");
            onMenuPress();
          }}
        >
          <View style={{ padding: moderateScale(4, 0.5) }}>
            <Menu01Icon size={iconSize.md} color="#a1a1aa" />
          </View>
        </Pressable>
      )}

      <View
        style={{ flex: 1, alignItems: "center", paddingHorizontal: spacing.sm }}
      >
        {isEditing ? (
          <View
            style={{
              width: "100%",
              backgroundColor: "rgba(0,187,255,0.08)",
              borderRadius: 8,
              paddingHorizontal: spacing.xs,
              paddingVertical: spacing.xs / 2,
            }}
          >
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
                width: "100%",
                color: "#ffffff",
                fontSize: fontSize.md,
                fontWeight: "600",
                textAlign: "center",
              }}
            />
          </View>
        ) : activeConversation ? (
          <Pressable onPress={startEditing}>
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
          </Pressable>
        ) : null}
      </View>

      <View
        style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}
      >
        {isEditing ? (
          <Pressable onPress={commitRename}>
            <View style={{ padding: moderateScale(4, 0.5) }}>
              <Tick01Icon size={iconSize.md} color="#00bbff" />
            </View>
          </Pressable>
        ) : (
          <>
            <Pressable
              onPress={() => {
                impactHaptic("light");
                router.push("/(app)/notifications");
              }}
              hitSlop={8}
            >
              <View style={{ padding: moderateScale(4, 0.5) }}>
                <Notification01Icon
                  size={iconSize.md}
                  color={hasUnread ? "#ffffff" : "#a1a1aa"}
                />
                {hasUnread ? (
                  <Animated.View
                    entering={ZoomIn.springify().damping(14).stiffness(300)}
                    style={{
                      position: "absolute",
                      top: moderateScale(4, 0.5),
                      right: moderateScale(4, 0.5),
                      width: 8,
                      height: 8,
                      borderRadius: 4,
                      backgroundColor: "#00bbff",
                      borderWidth: 1.5,
                      borderColor: "#111111",
                    }}
                  />
                ) : null}
              </View>
            </Pressable>
            <Pressable
              onPress={() => {
                impactHaptic("light");
                onNewChatPress();
              }}
            >
              <View style={{ padding: moderateScale(4, 0.5) }}>
                <PencilEdit02Icon size={iconSize.md} color="#a1a1aa" />
              </View>
            </Pressable>
          </>
        )}
      </View>
    </View>
  );
}
