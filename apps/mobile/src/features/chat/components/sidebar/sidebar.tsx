import { PortalHost } from "@rn-primitives/portal";
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
  return (
    <SafeAreaView className="flex-1 bg-[#141414]" edges={["top", "bottom"]}>
      <SidebarHeader onNewChat={onNewChat} />
      <ChatHistory onSelectChat={onSelectChat} />
      <SidebarFooter />
      <PortalHost name="sidebar-footer" />
    </SafeAreaView>
  );
}
