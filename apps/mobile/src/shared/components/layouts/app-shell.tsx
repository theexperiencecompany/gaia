import { type ReactNode, useCallback } from "react";
import { Keyboard, View } from "react-native";
import DrawerLayout, {
  DrawerPosition,
  DrawerState,
  DrawerType,
} from "react-native-gesture-handler/ReanimatedDrawerLayout";
import { SidebarContent } from "@/features/chat/components/sidebar/sidebar";
import { useSidebar } from "@/features/chat/hooks/sidebar-context";
import { useResponsive } from "@/lib/responsive";

interface AppShellProps {
  children: ReactNode;
}

/**
 * App-wide drawer host. Wraps any authenticated route group so that the
 * shared `SidebarContent` is reachable from every screen inside.
 *
 * Lives outside any feature folder because the drawer is no longer
 * chat-specific — chat, todos, and any future feature share the same
 * sidebar (with a contextual middle section keyed off the current
 * pathname). Mount this once per route group that should expose the
 * drawer; the underlying `useSidebar` context is provided by
 * `(app)/_layout.tsx`.
 */
export function AppShell({ children }: AppShellProps) {
  const { drawerRef } = useSidebar();
  const { sidebarWidth } = useResponsive();

  const renderDrawerContent = useCallback(() => <SidebarContent />, []);

  return (
    <View style={{ flex: 1, backgroundColor: "#111111" }}>
      <DrawerLayout
        ref={drawerRef}
        drawerWidth={sidebarWidth}
        drawerPosition={DrawerPosition.LEFT}
        drawerType={DrawerType.FRONT}
        overlayColor="rgba(0, 0, 0, 0.5)"
        renderNavigationView={renderDrawerContent}
        onDrawerStateChanged={(state) => {
          if (state !== DrawerState.IDLE) Keyboard.dismiss();
        }}
      >
        <View style={{ flex: 1 }}>{children}</View>
      </DrawerLayout>
    </View>
  );
}
