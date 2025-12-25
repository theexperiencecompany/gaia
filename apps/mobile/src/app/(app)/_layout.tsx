import { Redirect, Stack } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { HeroUINativeProvider } from "heroui-native";
import { useAuth } from "@/features/auth";

export default function AppLayout() {
  const { isAuthenticated, isLoading } = useAuth();

  // Show a loading screen while checking auth status
  if (isLoading) {
    return (
      <View className="flex-1 justify-center items-center bg-[#0a1929]">
        <ActivityIndicator size="large" color="#16c1ff" />
      </View>
    );
  }

  // If not authenticated, redirect to the login screen
  if (!isAuthenticated) {
    return <Redirect href="/login" />;
  }

  // If authenticated, render the children routes
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <HeroUINativeProvider>
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="index" />
          <Stack.Screen name="(chat)/[id]" />
        </Stack>
      </HeroUINativeProvider>
    </GestureHandlerRootView>
  );
}
