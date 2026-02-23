import { Redirect, Stack } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "@/features/auth";
import { SidebarProvider } from "@/features/chat";
import { NotificationProvider } from "@/features/notifications/components/notification-provider";

export default function AppLayout() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <View className="flex-1 justify-center items-center bg-[#0a1929]">
        <ActivityIndicator size="large" color="#16c1ff" />
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
              contentStyle: { backgroundColor: "#0a0a0a" },
              animation: "none",
              animationDuration: 0,
            }}
          >
            <Stack.Screen name="index" />
            <Stack.Screen name="test/index" />
          </Stack>
        </View>
      </SidebarProvider>
    </NotificationProvider>
  );
}
