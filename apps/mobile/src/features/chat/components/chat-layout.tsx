import { useRouter } from "expo-router";
import { type ReactNode, useCallback } from "react";
import { Keyboard, View } from "react-native";
import DrawerLayout, {
  DrawerPosition,
  DrawerState,
  DrawerType,
} from "react-native-gesture-handler/ReanimatedDrawerLayout";
import { SafeAreaView } from "react-native-safe-area-context";
import { chatApi } from "@/features/chat/api/chat-api";
import { useResponsive } from "@/lib/responsive";
import { useChatStore } from "@/stores/chat-store";
import { useSidebar } from "../hooks/sidebar-context";
import { useChatContext } from "../hooks/use-chat-context";
import { ChatHeader } from "./chat/chat-header";
import { SidebarContent } from "./sidebar/sidebar";

interface ChatLayoutProps {
  children: ReactNode;
  background?: ReactNode;
}

export function ChatLayout({ children, background }: ChatLayoutProps) {
  const { setActiveChatId, clearActiveMessages } = useChatContext();
  const { drawerRef, toggleSidebar, closeSidebar } = useSidebar();
  const { sidebarWidth } = useResponsive();
  const router = useRouter();

  const activeChatId = useChatStore((state) => state.activeChatId);
  const conversations = useChatStore((state) => state.conversations);
  const updateConversationTitle = useChatStore(
    (state) => state.updateConversationTitle,
  );
  const removeConversation = useChatStore((state) => state.removeConversation);
  const updateConversationStarred = useChatStore(
    (state) => state.updateConversationStarred,
  );

  const activeConversation = activeChatId
    ? conversations.find((c) => c.id === activeChatId)
    : null;

  const conversationTitle = activeConversation?.title ?? null;
  const isStarred = activeConversation?.is_starred ?? false;

  const handleSelectChat = useCallback(
    (chatId: string) => {
      closeSidebar();
      setActiveChatId(chatId);
    },
    [closeSidebar, setActiveChatId],
  );

  const handleNewChat = useCallback(() => {
    closeSidebar();
    clearActiveMessages();
    setActiveChatId(null);
    router.replace("/");
  }, [closeSidebar, clearActiveMessages, router, setActiveChatId]);

  const handleRename = useCallback(
    (newTitle: string) => {
      if (!activeChatId) return;
      updateConversationTitle(activeChatId, newTitle);
      void chatApi.renameConversation(activeChatId, newTitle);
    },
    [activeChatId, updateConversationTitle],
  );

  const handleDelete = useCallback(() => {
    if (!activeChatId) return;
    removeConversation(activeChatId);
    void chatApi.deleteConversation(activeChatId);
    clearActiveMessages();
    setActiveChatId(null);
    router.replace("/");
  }, [
    activeChatId,
    removeConversation,
    clearActiveMessages,
    setActiveChatId,
    router,
  ]);

  const handleStar = useCallback(() => {
    if (!activeChatId) return;
    const newStarred = !isStarred;
    updateConversationStarred(activeChatId, newStarred);
    void chatApi.toggleStarConversation(activeChatId, newStarred);
  }, [activeChatId, isStarred, updateConversationStarred]);

  const renderDrawerContent = useCallback(
    () => (
      <SidebarContent
        onSelectChat={handleSelectChat}
        onNewChat={handleNewChat}
      />
    ),
    [handleSelectChat, handleNewChat],
  );

  return (
    <View style={{ flex: 1 }}>
      <DrawerLayout
        ref={drawerRef}
        drawerWidth={sidebarWidth}
        drawerPosition={DrawerPosition.LEFT}
        drawerType={DrawerType.FRONT}
        overlayColor="rgba(0, 0, 0, 0.7)"
        renderNavigationView={renderDrawerContent}
        onDrawerStateChanged={(state) => {
          if (state !== DrawerState.IDLE) Keyboard.dismiss();
        }}
      >
        <View style={{ flex: 1 }}>
          {background && (
            <View
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
              }}
            >
              {background}
            </View>
          )}

          <SafeAreaView style={{ flex: 1 }} edges={["top"]}>
            <ChatHeader
              onMenuPress={toggleSidebar}
              onNewChatPress={handleNewChat}
              conversationTitle={conversationTitle ?? undefined}
              isStarred={isStarred}
              onStarPress={handleStar}
              onRenamePress={handleRename}
              onDeletePress={handleDelete}
            />

            {/* This must be flex:1 so KeyboardAvoidingView can resize */}
            <View style={{ flex: 1 }}>{children}</View>
          </SafeAreaView>
        </View>
      </DrawerLayout>
    </View>
  );
}
