import { useRouter } from "expo-router";
import { type ReactNode, useCallback } from "react";
import { View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useSidebar } from "../hooks/sidebar-context";
import { useChatContext } from "../hooks/use-chat-context";
import { ChatHeader } from "./chat/chat-header";

interface ChatLayoutProps {
  children: ReactNode;
  background?: ReactNode;
}

/**
 * Chat-specific in-screen frame: header + optional background art + body.
 * The drawer/sidebar lives at the app level (`AppShell`); this component
 * only owns the chat header and its hooks (toggle drawer, new chat).
 */
export function ChatLayout({ children, background }: ChatLayoutProps) {
  const { setActiveChatId, clearActiveMessages } = useChatContext();
  const { closeSidebar } = useSidebar();
  const router = useRouter();

  const handleNewChat = useCallback(() => {
    closeSidebar();
    clearActiveMessages();
    setActiveChatId(null);
    router.replace("/");
  }, [closeSidebar, clearActiveMessages, router, setActiveChatId]);

  return (
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
        <ChatHeader onNewChatPress={handleNewChat} />

        <View style={{ flex: 1 }}>{children}</View>
      </SafeAreaView>
    </View>
  );
}
