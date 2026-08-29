import { colorTokens } from "@gaia/shared/design";
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
 * App-wide drawer host — spacing + color tokens from shared.
 * - backgroundColor: colorTokens.primaryBg (#111111) — same as web --color-primary-bg
 * - drawerWidth: responsive sidebarWidth (85%/80%/75% cap 340) — mirrors web sidebarTokens.dark.width (260px) for web parity,
 *   but adapts for small screens (shared sidebar token is the web baseline).
 * - overlayColor: rgba(0,0,0,0.5) — same as web drawer overlay
 *
 * @see libs/shared/ts/src/design/tokens.generated.ts
 * @see apps/web/src/components/layout/sidebar/MainSidebar.tsx
 */
export function AppShell({ children }: AppShellProps) {
  const { drawerRef, _notifyDrawerOpened, _notifyDrawerClosed } = useSidebar();
  const { sidebarWidth } = useResponsive();

  const renderDrawerContent = useCallback(() => <SidebarContent />, []);

  return (
    <View style={{ flex: 1, backgroundColor: colorTokens.primaryBg }}>
      <DrawerLayout
        ref={drawerRef}
        drawerWidth={sidebarWidth}
        drawerPosition={DrawerPosition.LEFT}
        drawerType={DrawerType.FRONT}
        overlayColor="rgba(0, 0, 0, 0.5)"
        renderNavigationView={renderDrawerContent}
        onDrawerStateChanged={(state, drawerWillShow) => {
          if (state !== DrawerState.IDLE) Keyboard.dismiss();
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
