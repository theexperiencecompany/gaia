import { usePathname, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  AppIcon,
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
              // 14dp vertical → ~44dp tap target with icon/text height
              paddingVertical: 14,
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

      <Text
        style={{
          fontSize: fontSize.xs,
          fontWeight: "500",
          // tracking-wider equivalent: ~0.8px on 10px base
          letterSpacing: 0.8,
          textTransform: "uppercase",
          color: "#52525b",
          paddingHorizontal: spacing.sm + 4,
          paddingTop: spacing.md,
          paddingBottom: spacing.xs,
        }}
      >
        Chats
      </Text>
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
