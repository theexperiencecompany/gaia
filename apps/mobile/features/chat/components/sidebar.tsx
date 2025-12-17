/**
 * Sidebar Component
 * Drawer sidebar with chat history using react-native-gesture-handler
 */

import { StyleSheet, View } from "react-native";
import { ChatTheme } from "@/shared/constants/chat-theme";
import { ChatHistory } from "./chat-history";
import { SidebarFooter } from "./sidebar-footer";
import { SidebarHeader } from "./sidebar-header";

interface SidebarProps {
  onClose: () => void;
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
}

export const SIDEBAR_WIDTH = 280;

export function SidebarContent({
  onClose,
  onSelectChat,
  onNewChat,
}: SidebarProps) {
  return (
    <View style={styles.sidebar}>
      <SidebarHeader onClose={onClose} />
      <ChatHistory onSelectChat={onSelectChat} onNewChat={onNewChat} />
      <SidebarFooter />
    </View>
  );
}

const styles = StyleSheet.create({
  sidebar: {
    flex: 1,
    backgroundColor: ChatTheme.background,
  },
});
