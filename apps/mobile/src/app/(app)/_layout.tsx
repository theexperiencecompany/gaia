import { Redirect, Stack } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { HeroUINativeProvider } from "heroui-native";
import { useAuth } from "@/features/auth";
import { StyledGestureHandlerRootView } from "@/lib/uniwind";

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
    <StyledGestureHandlerRootView className="flex-1 bg-background text-foreground">
      <HeroUINativeProvider>
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: "transparent" },
          }}
        >
          <Stack.Screen name="index" />
          <Stack.Screen name="(chat)/[id]" />
        </Stack>
      </HeroUINativeProvider>
    </StyledGestureHandlerRootView>
  );
}
