import {
  colorTokens,
  roundedTokens,
  sidebarTokens,
  spacingTokens,
} from "@gaia/shared/design";
import { usePathname, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
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
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { TodoSidebarSection } from "@/features/todos/components/navigation/todo-sidebar-section";
import { useWorkflows } from "@/features/workflows/hooks/use-workflows";
import { useResponsive } from "@/lib/responsive";
import { useSidebar } from "../../hooks/sidebar-context";
import { useChatContext } from "../../hooks/use-chat-context";
import { ChatHistory } from "./chat-history";
import { SidebarFooter } from "./sidebar-footer";
import { SidebarHeader } from "./sidebar-header";

/**
 * Sidebar — parity with web `apps/web/src/components/layout/sidebar/MainSidebar.tsx`.
 *
 * Web switches per route:
 *   /todos        → TodoSidebar (Projects/Priorities/Labels with counts)
 *   /integrations → IntegrationsSidebar (integration list + status dots, Create CTA)
 *   /workflows    → WorkflowsSidebar (workflow list + New Workflow CTA)
 *   /settings     → SettingsSidebar
 *   /mail         → EmailSidebar
 *   / and /c/*   → ChatsList (grouped conversations)
 *
 * Mobile drawer mirrors the same route switch, but reuses RN primitives and shared tokens:
 *   - Horizontal section padding from shared spacingTokens.md (12px) — same as web px-3
 *   - Radii from shared roundedTokens (10px = md, 12px = lg) — same as web rounded-xl
 *   - Brand/accent colors from shared colorTokens.primary (#00bbff) — same as web --color-primary
 *   - Sidebar width token from shared sidebarTokens.dark.width (260px) for web parity,
 *     but mobile lane uses responsive getSidebarWidth (85%/80%/75% cap 340) for small screens.
 *
 * @see apps/web/src/components/layout/sidebar/MainSidebar.tsx
 * @see apps/web/src/components/layout/sidebar/variants/*
 * @see libs/shared/ts/src/design/tokens.generated.ts
 */

// Shared tokens — single source of truth, no hard-coded hex/spacing drift
export const SIDEBAR_WIDTH = Number.parseInt(
  sidebarTokens.dark.width.replace("px", ""),
  10,
); // 260 (web token); mobile uses responsive sidebarWidth instead
export const SIDEBAR_SECTION_PADDING = Number.parseInt(
  spacingTokens.md.replace("px", ""),
  10,
); // 12
const SECTION_GAP = Number.parseInt(spacingTokens.sm.replace("px", ""), 10); // 8 — gap between nav + per-route section
const ACTIVE_BG = "rgba(0,187,255,0.10)"; // colorTokens.primary @ 10% — same as web bg-primary/10
const ACTIVE_BAR = colorTokens.primary; // #00bbff
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
              gap: Number.parseInt(spacingTokens.md.replace("px", ""), 10),
              paddingHorizontal: Number.parseInt(
                spacingTokens.md.replace("px", ""),
                10,
              ),
              paddingVertical: Number.parseInt(
                spacingTokens.md.replace("px", ""),
                10,
              ),
              borderRadius: Number.parseInt(
                roundedTokens.md.replace("px", ""),
                10,
              ),
              backgroundColor: active
                ? ACTIVE_BG
                : pressed
                  ? PRESSED_BG
                  : "transparent",
              overflow: "hidden",
            })}
          >
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

// ---------------------------------------------------------------------------
// Per-route variant sections — mobile parity for web's variants/*
// ---------------------------------------------------------------------------

function SectionHeader({ title }: { title: string }) {
  return (
    <View
      style={{
        paddingHorizontal: Number.parseInt(
          spacingTokens.md.replace("px", ""),
          10,
        ),
        paddingTop: Number.parseInt(spacingTokens.lg.replace("px", ""), 10),
        paddingBottom: 4,
      }}
    >
      <Text
        style={{
          fontSize: 11,
          fontWeight: "600",
          color: "#71717a",
          letterSpacing: 0.6,
          textTransform: "uppercase",
        }}
      >
        {title}
      </Text>
    </View>
  );
}

function IntegrationsSidebarSection() {
  const router = useRouter();
  const pathname = usePathname();
  const { closeSidebar } = useSidebar();
  const { integrations, isLoading } = useIntegrations();

  if (isLoading) {
    return (
      <View
        style={{
          paddingHorizontal: SIDEBAR_SECTION_PADDING,
          paddingVertical: 12,
          alignItems: "center",
        }}
      >
        <ActivityIndicator size="small" color={ACTIVE_BAR} />
      </View>
    );
  }

  if (integrations.length === 0) {
    return (
      <View style={{ paddingHorizontal: SIDEBAR_SECTION_PADDING }}>
        <SectionHeader title="Integrations" />
        <Text
          style={{
            fontSize: 12,
            color: "#52525b",
            fontStyle: "italic",
            paddingHorizontal: 12,
            paddingVertical: 8,
          }}
        >
          No integrations yet
        </Text>
      </View>
    );
  }

  return (
    <View style={{ paddingHorizontal: SIDEBAR_SECTION_PADDING, gap: 2 }}>
      <SectionHeader title="Integrations" />
      {integrations.slice(0, 8).map((integration) => {
        const isActive = pathname.includes(`/integrations/${integration.id}`);
        return (
          <Pressable
            key={integration.id}
            onPress={() => {
              closeSidebar();
              router.push(`/integrations` as never);
            }}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              gap: 12,
              paddingHorizontal: 12,
              paddingVertical: 10,
              borderRadius: Number.parseInt(
                roundedTokens.md.replace("px", ""),
                10,
              ),
              backgroundColor: isActive
                ? ACTIVE_BG
                : pressed
                  ? PRESSED_BG
                  : "transparent",
              overflow: "hidden",
            })}
          >
            {isActive ? (
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
                icon={ConnectIcon}
                size={18}
                color={isActive ? ACTIVE_BAR : "#a1a1aa"}
              />
            </View>
            <Text
              style={{
                fontSize: 14,
                fontWeight: isActive ? "600" : "500",
                color: isActive ? "#ffffff" : "#e4e4e7",
                flex: 1,
              }}
              numberOfLines={1}
            >
              {integration.name}
            </Text>
            <View
              style={{
                width: 6,
                height: 6,
                borderRadius: 3,
                backgroundColor:
                  integration.status === "connected"
                    ? "#22c55e"
                    : integration.status === "created"
                      ? "#eab308"
                      : "transparent",
              }}
            />
          </Pressable>
        );
      })}
    </View>
  );
}

function WorkflowsSidebarSection() {
  const router = useRouter();
  const pathname = usePathname();
  const { closeSidebar } = useSidebar();
  const { workflows, isLoading } = useWorkflows();

  if (isLoading) {
    return (
      <View
        style={{
          paddingHorizontal: SIDEBAR_SECTION_PADDING,
          paddingVertical: 12,
          alignItems: "center",
        }}
      >
        <ActivityIndicator size="small" color={ACTIVE_BAR} />
      </View>
    );
  }

  if (workflows.length === 0) {
    return (
      <View style={{ paddingHorizontal: SIDEBAR_SECTION_PADDING }}>
        <SectionHeader title="Workflows" />
        <Text
          style={{
            fontSize: 12,
            color: "#52525b",
            fontStyle: "italic",
            paddingHorizontal: 12,
            paddingVertical: 8,
          }}
        >
          No workflows yet
        </Text>
      </View>
    );
  }

  return (
    <View style={{ paddingHorizontal: SIDEBAR_SECTION_PADDING, gap: 2 }}>
      <SectionHeader title="Workflows" />
      {workflows.slice(0, 8).map((workflow) => {
        const isActive = pathname.includes(workflow.id);
        return (
          <Pressable
            key={workflow.id}
            onPress={() => {
              closeSidebar();
              router.push(`/(app)/workflows/${workflow.id}` as never);
            }}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              gap: 12,
              paddingHorizontal: 12,
              paddingVertical: 10,
              borderRadius: Number.parseInt(
                roundedTokens.md.replace("px", ""),
                10,
              ),
              backgroundColor: isActive
                ? ACTIVE_BG
                : pressed
                  ? PRESSED_BG
                  : "transparent",
              overflow: "hidden",
            })}
          >
            {isActive ? (
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
                icon={ZapIcon}
                size={18}
                color={isActive ? ACTIVE_BAR : "#a1a1aa"}
              />
            </View>
            <Text
              style={{
                fontSize: 14,
                fontWeight: isActive ? "600" : "500",
                color: isActive ? "#ffffff" : "#e4e4e7",
                flex: 1,
              }}
              numberOfLines={1}
            >
              {workflow.title}
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
 *   - Per-route variant section:
 *       /todos        → TodoSidebarSection (Projects/Priorities/Labels)
 *       /integrations → IntegrationsSidebarSection (integration list)
 *       /workflows    → WorkflowsSidebarSection (workflow list)
 *   - Chat history: only on chat pages (/ and /c/:id)
 *   - Profile footer
 *
 * Spacing between sections uses shared spacingTokens.sm (8px) for parity with web space-y-2 (8px).
 */
export function SidebarContent() {
  const router = useRouter();
  const pathname = usePathname();
  const { closeSidebar } = useSidebar();
  const { setActiveChatId, clearActiveMessages } = useChatContext();
  const [chatSearch, setChatSearch] = useState("");

  const inTodos = pathname.startsWith("/todos");
  const inIntegrations = pathname.startsWith("/integrations");
  const inWorkflows = pathname.startsWith("/workflows");
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
      style={{ flex: 1, backgroundColor: colorTokens.secondaryBg }}
      edges={["top", "bottom"]}
    >
      <View style={{ flex: 1, gap: SECTION_GAP }}>
        <SidebarHeader
          searchQuery={chatSearch}
          onSearchChange={setChatSearch}
          onNewChat={inChats ? handleNewChat : undefined}
        />
        <SidebarNav />
        {inTodos ? <TodoSidebarSection /> : null}
        {inIntegrations ? <IntegrationsSidebarSection /> : null}
        {inWorkflows ? <WorkflowsSidebarSection /> : null}
        {inChats ? (
          <ChatHistory
            onSelectChat={handleSelectChat}
            searchQuery={chatSearch}
          />
        ) : !inTodos && !inIntegrations && !inWorkflows ? (
          <View style={{ flex: 1 }} />
        ) : null}
        <SidebarFooter />
      </View>
    </SafeAreaView>
  );
}
