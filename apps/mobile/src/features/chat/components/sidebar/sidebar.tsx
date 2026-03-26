import { Surface } from "heroui-native";
import { useState } from "react";
import { SafeAreaView } from "react-native-safe-area-context";
import { ChatHistory } from "./chat-history";
import { SidebarFooter } from "./sidebar-footer";
import { SidebarHeader } from "./sidebar-header";

interface SidebarProps {
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
  onClose?: () => void;
}

export const SIDEBAR_WIDTH = 300;

export function SidebarContent({
  onSelectChat,
  onNewChat,
  onClose,
}: SidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: "#0f1011" }}
      edges={["top", "bottom"]}
    >
      <Surface variant="transparent" style={{ flex: 1 }}>
        <SidebarHeader
          onNewChat={onNewChat}
          onClose={onClose}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />
        <ChatHistory onSelectChat={onSelectChat} searchQuery={searchQuery} />
        <SidebarFooter />
      </Surface>
    </SafeAreaView>
  );
}
