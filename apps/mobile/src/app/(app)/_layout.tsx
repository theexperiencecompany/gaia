import { Redirect, Stack } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "@/features/auth";
import { SidebarProvider } from "@/features/chat";
import { NotificationProvider } from "@/features/notifications/components/notification-provider";
import { getOnboardingStatus } from "@/features/onboarding/api/onboarding-api";
import { wsManager } from "@/lib/websocket-client";

export default function AppLayout() {
  const { isAuthenticated, isLoading } = useAuth();
  const [onboardingChecked, setOnboardingChecked] = useState(false);
  const [onboardingCompleted, setOnboardingCompleted] = useState(true);

  useEffect(() => {
    if (!isAuthenticated) {
      wsManager.disconnect();
      wsManager.unregisterAppStateHandler();
      return;
    }

    wsManager.connect();
    wsManager.registerAppStateHandler();

    return () => {
      wsManager.unregisterAppStateHandler();
      wsManager.disconnect();
    };
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) {
      setOnboardingChecked(true);
      return;
    }

    getOnboardingStatus()
      .then((status) => {
        setOnboardingCompleted(status.completed);
      })
      .catch(() => {
        // If the check fails (e.g. endpoint not yet deployed), default to completed
        // so existing users are not blocked.
        setOnboardingCompleted(true);
      })
      .finally(() => {
        setOnboardingChecked(true);
      });
  }, [isAuthenticated]);

  if (isLoading || !onboardingChecked) {
    return (
      <View className="flex-1 justify-center items-center bg-background">
        <ActivityIndicator size="large" color="#00bbff" />
      </View>
    );
  }

  if (!isAuthenticated) {
    return <Redirect href="/login" />;
  }

  if (!onboardingCompleted) {
    return <Redirect href="/(app)/onboarding" />;
  }

  return (
    <NotificationProvider>
      <SidebarProvider>
        <View className="flex-1 bg-background">
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: "#060a14" },
              animation: "slide_from_right",
              animationDuration: 280,
            }}
          >
            <Stack.Screen
              name="(tabs)"
              options={{ animation: "none", animationDuration: 0 }}
            />
            <Stack.Screen name="c/[id]" options={{ animation: "none" }} />
            <Stack.Screen
              name="workflows/[id]"
              options={{ animation: "slide_from_right" }}
            />
            <Stack.Screen
              name="todos/project/[projectId]"
              options={{ animation: "slide_from_right" }}
            />
            <Stack.Screen
              name="settings/index"
              options={{ animation: "slide_from_right" }}
            />
            <Stack.Screen
              name="settings/usage"
              options={{ animation: "slide_from_right" }}
            />
            <Stack.Screen
              name="skills/index"
              options={{
                animation: "slide_from_bottom",
                presentation: "modal",
              }}
            />
            <Stack.Screen
              name="tools/index"
              options={{
                animation: "slide_from_bottom",
                presentation: "modal",
              }}
            />
            <Stack.Screen
              name="calendar/index"
              options={{ animation: "slide_from_right" }}
            />
            <Stack.Screen
              name="memory/index"
              options={{ animation: "slide_from_right" }}
            />
            <Stack.Screen name="test/index" />
            <Stack.Screen name="search/index" options={{ animation: "fade" }} />
            <Stack.Screen
              name="notes/index"
              options={{ animation: "slide_from_right" }}
            />
            <Stack.Screen
              name="profile-card/index"
              options={{
                animation: "slide_from_bottom",
                presentation: "modal",
              }}
            />
            <Stack.Screen
              name="onboarding/index"
              options={{ animation: "fade" }}
            />
          </Stack>
        </View>
      </SidebarProvider>
    </NotificationProvider>
  );
}
