import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { ChatHistory } from "./chat-history";
import { SidebarFooter } from "./sidebar-footer";
import { SidebarHeader } from "./sidebar-header";

interface SidebarProps {
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
}

export const SIDEBAR_WIDTH = 300;

export function SidebarContent({ onSelectChat, onNewChat }: SidebarProps) {
  const router = useRouter();

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: "#141414" }}
      edges={["top", "bottom"]}
    >
      <SidebarHeader
        onNewChat={onNewChat}
        onOpenIntegrations={() => router.push("/(app)/integrations")}
        onOpenWorkflows={() => router.push("/(app)/workflows")}
      />
      <ChatHistory onSelectChat={onSelectChat} />
      <SidebarFooter />
    </SafeAreaView>
  );
}
