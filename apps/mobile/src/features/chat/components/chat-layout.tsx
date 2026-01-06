import { useRouter } from "expo-router";
import { type ReactNode, useCallback } from "react";
import { Keyboard, View } from "react-native";
import DrawerLayout, {
  DrawerPosition,
  DrawerState,
  DrawerType,
} from "react-native-gesture-handler/ReanimatedDrawerLayout";
import { SafeAreaView } from "react-native-safe-area-context";
import { ChatHeader, SIDEBAR_WIDTH, SidebarContent } from "@/features/chat";
import { useChatContext } from "@/features/chat/hooks/use-chat-context";
import { useSidebar } from "@/features/chat/hooks/sidebar-context";

interface ChatLayoutProps {
  children: ReactNode;
}

export function ChatLayout({ children }: ChatLayoutProps) {
  const router = useRouter();
  const { setActiveChatId } = useChatContext();
  const { drawerRef, toggleSidebar, closeSidebar } = useSidebar();

  const handleSelectChat = useCallback(
    (chatId: string) => {
      setActiveChatId(chatId);
      closeSidebar();
      router.replace(`/(chat)/${chatId}`);
    },
    [closeSidebar, router, setActiveChatId]
  );

  const handleNewChat = useCallback(() => {
    closeSidebar();
    setActiveChatId(null);
    router.replace("/");
  }, [closeSidebar, router, setActiveChatId]);

  const renderDrawerContent = useCallback(
    () => (
      <SidebarContent
        onSelectChat={handleSelectChat}
        onNewChat={handleNewChat}
      />
    ),
    [handleSelectChat, handleNewChat]
  );

  return (
    <View className="flex-1">
      <DrawerLayout
        ref={drawerRef}
        drawerWidth={SIDEBAR_WIDTH}
        drawerPosition={DrawerPosition.LEFT}
        drawerType={DrawerType.FRONT}
        overlayColor="rgba(0, 0, 0, 0.7)"
        renderNavigationView={renderDrawerContent}
        onDrawerStateChanged={(newState) => {
          if (newState !== DrawerState.IDLE) Keyboard.dismiss();
        }}
      >
        <View className="flex-1">
          <SafeAreaView style={{ flex: 1 }} edges={["top"]}>
            <ChatHeader
              onMenuPress={toggleSidebar}
              onNewChatPress={handleNewChat}
              onSearchPress={() => console.log("Search pressed")}
            />
            {children}
          </SafeAreaView>
        </View>
      </DrawerLayout>
    </View>
  );
}
