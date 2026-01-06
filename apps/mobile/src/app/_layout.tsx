import "../../global.css";
import "react-native-gesture-handler";
import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  useFonts,
} from "@expo-google-fonts/inter";
import {
  RobotoMono_400Regular,
  RobotoMono_500Medium,
} from "@expo-google-fonts/roboto-mono";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { HeroUINativeProvider } from "heroui-native";
import { useEffect } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import "react-native-reanimated";
import { Uniwind } from "uniwind";

import { AuthProvider } from "@/features/auth";
import { ChatProvider } from "@/features/chat";
import { QueryProvider } from "@/lib/query-provider";

SplashScreen.preventAutoHideAsync();

Uniwind.setTheme("dark");

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
    RobotoMono_400Regular,
    RobotoMono_500Medium,
  });
  useEffect(() => {
    if (fontsLoaded) {
      SplashScreen.hideAsync();
    }
  }, [fontsLoaded]);

  if (!fontsLoaded) {
    return null;
  }

  return (
    <QueryProvider>
      <AuthProvider>
        <ChatProvider>
          <GestureHandlerRootView style={{ flex: 1 }} className="bg:dark">
            <HeroUINativeProvider>
              <Stack screenOptions={{ headerShown: false }}>
                <Stack.Screen name="(app)" options={{ headerShown: false }} />
                <Stack.Screen
                  name="login/index"
                  options={{ headerShown: false }}
                />
                <Stack.Screen
                  name="signup/index"
                  options={{ headerShown: false }}
                />
              </Stack>
              <StatusBar style="auto" />
            </HeroUINativeProvider>
          </GestureHandlerRootView>
        </ChatProvider>
      </AuthProvider>
    </QueryProvider>
  );
}
