import { usePathname, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  AppIcon,
  BubbleChatAddIcon,
  CheckListIcon,
  ConnectIcon,
  ZapIcon,
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

const ACTIVE_BG = "rgba(255,255,255,0.05)";
const ACTIVE_TEXT = "#e4e4e7";
const INACTIVE_TEXT = "#71717a";

const NAV_ITEMS = [
  {
    icon: CheckListIcon,
    label: "Tasks",
    route: "/(app)/(tabs)/todos",
    matchPrefix: "/todos",
  },
  {
    icon: ConnectIcon,
    label: "Integrations",
    route: "/(app)/(tabs)/integrations",
    matchPrefix: "/integrations",
  },
  {
    icon: ZapIcon,
    label: "Workflows",
    route: "/(app)/(tabs)/workflows",
    matchPrefix: "/workflows",
  },
];

function SidebarNav() {
  const router = useRouter();
  const pathname = usePathname();
  const { spacing, fontSize, iconSize } = useResponsive();

  const isActive = (matchPrefix: string) => pathname.includes(matchPrefix);

  return (
    <View style={{ paddingHorizontal: spacing.xs }}>
      {NAV_ITEMS.map((item) => {
        const active = isActive(item.matchPrefix);
        return (
          <Pressable
            key={item.label}
            onPress={() => router.push(item.route as never)}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
              paddingHorizontal: spacing.sm + 4,
              // 8dp vertical → tighter, web-like density (~40dp tap target with icon height)
              paddingVertical: 8,
              borderRadius: 12,
              backgroundColor: active || pressed ? ACTIVE_BG : "transparent",
            })}
          >
            {/* Left active indicator — 2dp line matching accent */}
            <View
              style={{
                position: "absolute",
                left: 0,
                top: 10,
                bottom: 10,
                width: 2,
                borderRadius: 1,
                backgroundColor: active ? "#00bbff" : "transparent",
              }}
            />
            <View
              style={{
                width: 20,
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <AppIcon
                icon={item.icon}
                size={iconSize.sm}
                color={active ? "#00bbff" : INACTIVE_TEXT}
              />
            </View>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: active ? ACTIVE_TEXT : INACTIVE_TEXT,
                fontWeight: active ? "500" : "400",
              }}
            >
              {item.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

interface NewChatButtonProps {
  onPress: () => void;
}

function NewChatButton({ onPress }: NewChatButtonProps) {
  const { spacing, fontSize, iconSize } = useResponsive();
  return (
    <View
      style={{
        paddingHorizontal: spacing.sm,
        paddingTop: spacing.sm,
        paddingBottom: spacing.xs,
      }}
    >
      <Pressable
        onPress={onPress}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          paddingHorizontal: spacing.sm + 4,
          paddingVertical: 8,
          borderRadius: 12,
          backgroundColor: pressed
            ? "rgba(0,187,255,0.18)"
            : "rgba(0,187,255,0.1)",
        })}
      >
        <AppIcon icon={BubbleChatAddIcon} size={iconSize.sm} color="#00bbff" />
        <Text
          style={{
            fontSize: fontSize.sm,
            color: "#00bbff",
            fontWeight: "500",
          }}
        >
          New Chat
        </Text>
      </Pressable>
    </View>
  );
}

export function SidebarContent({ onSelectChat, onNewChat }: SidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: "#1a1a1a" }}
      edges={["top", "bottom"]}
    >
      <View style={{ flex: 1 }}>
        <SidebarHeader
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />
        <SidebarNav />
        <NewChatButton onPress={onNewChat} />
        <ChatHistory onSelectChat={onSelectChat} searchQuery={searchQuery} />
        <SidebarFooter />
      </View>
    </SafeAreaView>
  );
}
