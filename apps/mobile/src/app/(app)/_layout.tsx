import { Redirect, Stack } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "@/features/auth";
import { SidebarProvider } from "@/features/chat";
import { NotificationProvider } from "@/features/notifications/components/notification-provider";

export default function AppLayout() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <View className="flex-1 justify-center items-center bg-background">
        <ActivityIndicator size="large" color="#00bbff" />
      </View>
    );
  }

  if (!isAuthenticated) {
    return <Redirect href="/login" />;
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
            }}
          >
            <Stack.Screen
              name="(tabs)"
              options={{ animation: "none", animationDuration: 0 }}
            />
            <Stack.Screen name="c/[id]" options={{ animation: "none" }} />
            <Stack.Screen name="workflows/[id]" />
            <Stack.Screen name="settings/index" />
            <Stack.Screen name="calendar/index" />
            <Stack.Screen name="test/index" />
          </Stack>
        </View>
      </SidebarProvider>
    </NotificationProvider>
  );
}
