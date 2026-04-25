import { usePathname, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  AppIcon,
  CheckListIcon,
  ConnectIcon,
  LayoutGridIcon,
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

const ACTIVE_BG = "rgba(255,255,255,0.08)";
const ACTIVE_TEXT = "#e4e4e7";
const INACTIVE_TEXT = "#71717a";
const DIVIDER_COLOR = "#27272a";
const SECTION_LABEL_COLOR = "#52525b";

const NAV_ITEMS = [
  {
    icon: LayoutGridIcon,
    label: "Home",
    route: "/(app)/(tabs)/home",
    matchPrefix: "/home",
  },
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
    <View style={{ paddingHorizontal: spacing.xs, paddingBottom: 4 }}>
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
              paddingVertical: 11,
              borderRadius: 8,
              backgroundColor: active || pressed ? ACTIVE_BG : "transparent",
            })}
          >
            <View
              style={{
                width: 18,
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <AppIcon
                icon={item.icon}
                size={iconSize.sm}
                color={active ? ACTIVE_TEXT : INACTIVE_TEXT}
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

      <View
        style={{
          height: 1,
          backgroundColor: DIVIDER_COLOR,
          marginHorizontal: spacing.sm,
          marginTop: 8,
          marginBottom: 2,
        }}
      />
      <Text
        style={{
          fontSize: 10,
          fontWeight: "600",
          letterSpacing: 0.8,
          textTransform: "uppercase",
          color: SECTION_LABEL_COLOR,
          paddingHorizontal: spacing.sm + 4,
          paddingTop: 8,
          paddingBottom: 2,
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
