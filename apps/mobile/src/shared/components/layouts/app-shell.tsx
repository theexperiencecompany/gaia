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
 * App-wide drawer host, wrapping any authenticated route group so the shared
 * `SidebarContent` is reachable everywhere. Lives outside any feature folder
 * since chat, todos, and future features share one sidebar (contextual middle
 * section keyed off pathname); mount once per route group — `useSidebar` context comes from `(app)/_layout.tsx`.
 */
export function AppShell({ children }: AppShellProps) {
  const { drawerRef, _notifyDrawerOpened, _notifyDrawerClosed } = useSidebar();
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
        onDrawerStateChanged={(state, drawerWillShow) => {
          if (state !== DrawerState.IDLE) Keyboard.dismiss();
          // Keep sidebar context in sync with the actual drawer state so
          // swipe-to-dismiss doesn't desync the toggle button.
          if (state === DrawerState.SETTLING) {
            if (drawerWillShow) _notifyDrawerOpened();
            else _notifyDrawerClosed();
          }
        }}
        onDrawerOpen={_notifyDrawerOpened}
        onDrawerClose={_notifyDrawerClosed}
      >
        <View style={{ flex: 1 }}>{children}</View>
      </DrawerLayout>
    </View>
  );
}
