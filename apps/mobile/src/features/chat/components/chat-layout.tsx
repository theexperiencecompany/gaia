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
  const { setActiveChatId, clearActiveMessages } = useChatContext();
  const { drawerRef, toggleSidebar, closeSidebar } = useSidebar();

  const handleSelectChat = useCallback(
    (chatId: string) => {
      setActiveChatId(chatId);
    },
    [setActiveChatId]
  );

  const handleNewChat = useCallback(() => {
    closeSidebar();
    clearActiveMessages();
    setActiveChatId(null);
  }, [closeSidebar, clearActiveMessages, setActiveChatId]);

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
          {children}
          <SafeAreaView
            style={{ position: "absolute", top: 0, left: 0, right: 0 }}
            edges={["top"]}
          >
            <ChatHeader
              onMenuPress={toggleSidebar}
              onNewChatPress={handleNewChat}
              onSearchPress={() => console.log("Search pressed")}
            />
          </SafeAreaView>
        </View>
      </DrawerLayout>
    </View>
  );
}
