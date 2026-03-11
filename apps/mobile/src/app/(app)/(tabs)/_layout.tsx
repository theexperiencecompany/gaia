import { Tabs } from "expo-router";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import type { AnyIcon } from "@/components/icons";
import {
  AppIcon,
  BubbleChatIcon,
  CheckListIcon,
  ConnectIcon,
  LayoutGridIcon,
  Notification01Icon,
  ZapIcon,
} from "@/components/icons";
import { selectionHaptic } from "@/lib/haptics";

const TAB_BAR_BG = "#0f1011";
const ACTIVE_COLOR = "#00bbff";
const INACTIVE_COLOR = "#8e8e93";

function TabIcon({ icon, color }: { icon: AnyIcon; color: string }) {
  return <AppIcon icon={icon} size={22} color={color} />;
}

export default function TabsLayout() {
  return (
    <ErrorBoundary>
      <Tabs
        screenListeners={{
          tabPress: () => {
            selectionHaptic();
          },
        }}
        screenOptions={{
          headerShown: false,
          tabBarStyle: {
            backgroundColor: TAB_BAR_BG,
            borderTopColor: "rgba(255,255,255,0.08)",
            borderTopWidth: 1,
            height: 56,
            paddingBottom: 6,
            paddingTop: 6,
          },
          tabBarActiveTintColor: ACTIVE_COLOR,
          tabBarInactiveTintColor: INACTIVE_COLOR,
          tabBarLabelStyle: {
            fontSize: 10,
            fontWeight: "500",
            marginTop: 2,
          },
        }}
      >
        <Tabs.Screen
          name="home"
          options={{
            title: "Home",
            tabBarIcon: ({ color }) => (
              <TabIcon icon={LayoutGridIcon} color={color} />
            ),
          }}
        />
        <Tabs.Screen
          name="index"
          options={{
            title: "Chat",
            tabBarIcon: ({ color }) => (
              <TabIcon icon={BubbleChatIcon} color={color} />
            ),
          }}
        />
        <Tabs.Screen
          name="todos"
          options={{
            title: "Todos",
            tabBarIcon: ({ color }) => (
              <TabIcon icon={CheckListIcon} color={color} />
            ),
          }}
        />
        <Tabs.Screen
          name="workflows"
          options={{
            title: "Workflows",
            tabBarIcon: ({ color }) => <TabIcon icon={ZapIcon} color={color} />,
          }}
        />
        <Tabs.Screen
          name="integrations"
          options={{
            title: "Integrations",
            tabBarIcon: ({ color }) => (
              <TabIcon icon={ConnectIcon} color={color} />
            ),
          }}
        />
        <Tabs.Screen
          name="notifications"
          options={{
            title: "Alerts",
            tabBarIcon: ({ color }) => (
              <TabIcon icon={Notification01Icon} color={color} />
            ),
          }}
        />
      </Tabs>
    </ErrorBoundary>
  );
}
