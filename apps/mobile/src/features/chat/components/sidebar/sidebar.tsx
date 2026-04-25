import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  AppIcon,
  Calendar03Icon,
  Flowchart01Icon,
  Notification01Icon,
  Settings02Icon,
  Wrench01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { ChatHistory } from "./chat-history";
import { SidebarFooter } from "./sidebar-footer";
import { SidebarHeader } from "./sidebar-header";

interface SidebarProps {
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
  onClose?: () => void;
}

export const SIDEBAR_WIDTH = 300;

const DIVIDER_COLOR = "#27272a";
const MUTED_COLOR = "#71717a";

function SidebarNav() {
  const router = useRouter();
  const { spacing, fontSize, iconSize } = useResponsive();

  const navItems = [
    {
      icon: Settings02Icon,
      label: "Settings",
      onPress: () => router.push("/(app)/settings"),
    },
    {
      icon: Wrench01Icon,
      label: "Integrations",
      onPress: () => router.push("/(app)/(tabs)/integrations"),
    },
    {
      icon: Flowchart01Icon,
      label: "Workflows",
      onPress: () => router.push("/(app)/(tabs)/workflows"),
    },
    {
      icon: Notification01Icon,
      label: "Notifications",
      onPress: () => router.push("/(app)/(tabs)/notifications"),
    },
    {
      icon: Calendar03Icon,
      label: "Calendar",
      onPress: () => router.push("/(app)/calendar"),
    },
  ];

  return (
    <View style={{ paddingHorizontal: spacing.xs, paddingBottom: spacing.xs }}>
      {navItems.map((item) => (
        <Pressable
          key={item.label}
          onPress={item.onPress}
          style={({ pressed }) => ({
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
            paddingHorizontal: spacing.sm + 2,
            paddingVertical: spacing.sm + 1,
            borderRadius: 8,
            backgroundColor: pressed ? "rgba(255,255,255,0.05)" : "transparent",
          })}
        >
          <AppIcon
            icon={item.icon}
            size={iconSize.sm - 1}
            color={MUTED_COLOR}
          />
          <Text
            style={{
              fontSize: fontSize.sm,
              color: MUTED_COLOR,
              fontWeight: "500",
            }}
          >
            {item.label}
          </Text>
        </Pressable>
      ))}
      <View
        style={{
          height: 1,
          backgroundColor: DIVIDER_COLOR,
          marginHorizontal: spacing.sm,
          marginTop: spacing.xs,
        }}
      />
    </View>
  );
}

export function SidebarContent({ onSelectChat, onNewChat }: SidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: "#0f1011" }}
      edges={["top", "bottom"]}
    >
      <View style={{ flex: 1 }}>
        <SidebarHeader
          onNewChat={onNewChat}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />
        <SidebarNav />
        <ChatHistory onSelectChat={onSelectChat} searchQuery={searchQuery} />
        <SidebarFooter />
      </View>
    </SafeAreaView>
  );
}
