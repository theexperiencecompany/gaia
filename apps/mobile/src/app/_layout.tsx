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
import { PortalHost } from "@rn-primitives/portal";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { View } from "react-native";
import "react-native-reanimated";

import "../../global.css";
import { colorScheme } from "nativewind";
import { AuthProvider } from "@/features/auth";
import { ChatProvider } from "@/features/chat";

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  colorScheme.set("dark");

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
    <AuthProvider>
      <ChatProvider>
        <View style={{ flex: 1 }}>
          <Stack screenOptions={{ headerShown: false }}>
            <Stack.Screen name="(app)" options={{ headerShown: false }} />
            <Stack.Screen name="login/index" options={{ headerShown: false }} />
            <Stack.Screen
              name="signup/index"
              options={{ headerShown: false }}
            />
          </Stack>
          <PortalHost />
          <StatusBar style="auto" />
        </View>
      </ChatProvider>
    </AuthProvider>
  );
}
