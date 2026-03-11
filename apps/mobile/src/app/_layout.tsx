import "../../global.css";
import "react-native-gesture-handler";
if (__DEV__) require("../lib/reactotron");

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
import { BottomSheetModalProvider } from "@gorhom/bottom-sheet";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { HeroUINativeProvider } from "heroui-native";
import { useEffect } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import "react-native-reanimated";
import { Pressable, Text, View } from "react-native";
import { Uniwind } from "uniwind";

import { AuthProvider } from "@/features/auth";
import { ChatProvider } from "@/features/chat";
import { QueryProvider } from "@/lib/query-provider";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { useAppTheme } from "@/shared/hooks/use-app-theme";

SplashScreen.preventAutoHideAsync();

function CrashRecoveryFallback() {
  return (
    <View
      style={{ flex: 1, backgroundColor: "#060a14" }}
      className="items-center justify-center p-8"
    >
      <Text className="text-white text-2xl font-bold mb-3 text-center">
        App Crashed
      </Text>
      <Text className="text-gray-400 text-center text-sm leading-5 mb-8 max-w-xs">
        An unexpected error occurred. Please restart the app to continue.
      </Text>
      <Pressable
        onPress={() => SplashScreen.preventAutoHideAsync()}
        className="bg-primary px-8 py-3 rounded-lg"
      >
        <Text className="text-white font-semibold">Restart App</Text>
      </Pressable>
    </View>
  );
}

function ThemeProvider({ children }: { children: React.ReactNode }) {
  const activeTheme = useAppTheme();

  useEffect(() => {
    Uniwind.setTheme(activeTheme);
  }, [activeTheme]);

  return <>{children}</>;
}

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
    <ErrorBoundary fallback={<CrashRecoveryFallback />}>
      <QueryProvider>
        <AuthProvider>
          <ChatProvider>
            <ThemeProvider>
              <GestureHandlerRootView
                style={{ flex: 1, backgroundColor: "#060a14" }}
              >
                <HeroUINativeProvider>
                  <BottomSheetModalProvider>
                    <Stack screenOptions={{ headerShown: false }}>
                      <Stack.Screen
                        name="(app)"
                        options={{ headerShown: false }}
                      />
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
                  </BottomSheetModalProvider>
                </HeroUINativeProvider>
              </GestureHandlerRootView>
            </ThemeProvider>
          </ChatProvider>
        </AuthProvider>
      </QueryProvider>
    </ErrorBoundary>
  );
}
