import { usePathname, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import type { AnyIcon } from "@/components/icons";
import {
  AppIcon,
  CheckListIcon,
  ConnectIcon,
  MessageMultiple01Icon,
  ZapIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { TodoSidebarSection } from "@/features/todos/components/navigation/todo-sidebar-section";
import { useResponsive } from "@/lib/responsive";
import { useSidebar } from "../../hooks/sidebar-context";
import { useChatContext } from "../../hooks/use-chat-context";
import { ChatHistory } from "./chat-history";
import { SidebarFooter } from "./sidebar-footer";
import { SidebarHeader } from "./sidebar-header";

export const SIDEBAR_WIDTH = 300;
export const SIDEBAR_SECTION_PADDING = 12;

const ACTIVE_BG = "rgba(0,187,255,0.10)";
const ACTIVE_BAR = "#00bbff";
const ACTIVE_TEXT = "#ffffff";
const INACTIVE_TEXT = "#a1a1aa";
const PRESSED_BG = "rgba(255,255,255,0.04)";

interface NavItem {
  icon: AnyIcon;
  label: string;
  route: string;
  matchPrefix?: string;
  matchFn?: (pathname: string) => boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    icon: CheckListIcon,
    label: "Tasks",
    route: "/(app)/(tabs)/todos",
    matchPrefix: "/todos",
  },
  {
    icon: ConnectIcon,
    label: "Integrations",
    route: "/(app)/integrations",
    matchPrefix: "/integrations",
  },
  {
    icon: ZapIcon,
    label: "Workflows",
    route: "/(app)/(tabs)/workflows",
    matchPrefix: "/workflows",
  },
  {
    icon: MessageMultiple01Icon,
    label: "Chats",
    route: "/",
    matchFn: (pathname) => pathname === "/" || pathname.startsWith("/c/"),
  },
];

function SidebarNav() {
  const router = useRouter();
  const pathname = usePathname();
  const { closeSidebar } = useSidebar();
  const { fontSize, iconSize } = useResponsive();

  const isItemActive = (item: NavItem) => {
    if (item.matchFn) return item.matchFn(pathname);
    return item.matchPrefix ? pathname.includes(item.matchPrefix) : false;
  };

  return (
    <View style={{ paddingHorizontal: SIDEBAR_SECTION_PADDING, gap: 2 }}>
      {NAV_ITEMS.map((item) => {
        const active = isItemActive(item);
        return (
          <Pressable
            key={item.label}
            onPress={() => {
              closeSidebar();
              router.push(item.route as never);
            }}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              gap: 12,
              paddingHorizontal: 12,
              paddingVertical: 12,
              borderRadius: 10,
              backgroundColor: active
                ? ACTIVE_BG
                : pressed
                  ? PRESSED_BG
                  : "transparent",
              overflow: "hidden",
            })}
          >
            {/* Full-height active accent bar on the left */}
            {active ? (
              <View
                style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: 3,
                  backgroundColor: ACTIVE_BAR,
                }}
              />
            ) : null}
            <View
              style={{
                width: 22,
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <AppIcon
                icon={item.icon}
                size={iconSize.md}
                color={active ? ACTIVE_BAR : INACTIVE_TEXT}
              />
            </View>
            <Text
              style={{
                fontSize: fontSize.md,
                color: active ? ACTIVE_TEXT : INACTIVE_TEXT,
                fontWeight: active ? "600" : "400",
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

/**
 * Shared app sidebar.
 *
 * Layout (top → bottom):
 *   - Branding + new chat icon + conversation search
 *   - Main nav (Chats / Tasks / Integrations / Workflows)
 *   - Feature-specific section: only on /todos (Projects / Priorities / Labels)
 *   - Chat history: only on chat pages (/ and /c/:id)
 *   - Profile footer
 */
export function SidebarContent() {
  const router = useRouter();
  const pathname = usePathname();
  const { closeSidebar } = useSidebar();
  const { setActiveChatId, clearActiveMessages } = useChatContext();
  const [chatSearch, setChatSearch] = useState("");

  const inTodos = pathname.startsWith("/todos");
  const inChats = pathname === "/" || pathname.startsWith("/c/");

  const handleSelectChat = useCallback(
    (chatId: string) => {
      closeSidebar();
      setActiveChatId(chatId);
      router.push(`/c/${chatId}` as never);
    },
    [closeSidebar, setActiveChatId, router],
  );

  const handleNewChat = useCallback(() => {
    closeSidebar();
    clearActiveMessages();
    setActiveChatId(null);
    router.replace("/");
  }, [closeSidebar, clearActiveMessages, router, setActiveChatId]);

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: "#1a1a1a" }}
      edges={["top", "bottom"]}
    >
      <View style={{ flex: 1 }}>
        <SidebarHeader
          searchQuery={chatSearch}
          onSearchChange={setChatSearch}
          onNewChat={inChats ? handleNewChat : undefined}
        />
        <SidebarNav />
        {inTodos ? <TodoSidebarSection /> : null}
        {inChats ? (
          <ChatHistory
            onSelectChat={handleSelectChat}
            searchQuery={chatSearch}
          />
        ) : (
          <View style={{ flex: 1 }} />
        )}
        <SidebarFooter />
      </View>
    </SafeAreaView>
  );
}
