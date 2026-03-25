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
import * as Linking from "expo-linking";
import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { HeroUINativeProvider } from "heroui-native";
import { useEffect } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import "react-native-reanimated";
import { Pressable, Text, View } from "react-native";
import { Uniwind } from "uniwind";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { OfflineBanner } from "@/components/OfflineBanner";
import { UpdateBanner } from "@/components/UpdateBanner";
import { AuthProvider } from "@/features/auth/hooks/use-auth";
import { ChatProvider } from "@/features/chat/hooks/use-chat-context";
import { trackScreen } from "@/lib/analytics";
import { getRouteForDeepLink, parseDeepLink } from "@/lib/deep-links";
import { QueryProvider } from "@/lib/query-provider";
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

function ScreenTracker() {
  const segments = useSegments();

  useEffect(() => {
    const screenName = segments.join("/") || "home";
    trackScreen(screenName);
  }, [segments]);

  return null;
}

function DeepLinkHandler() {
  const router = useRouter();

  useEffect(() => {
    const handleUrl = (event: { url: string }) => {
      const parsed = parseDeepLink(event.url);
      const route = getRouteForDeepLink(parsed);
      if (route) {
        router.push(route as Parameters<typeof router.push>[0]);
      }
    };

    const subscription = Linking.addEventListener("url", handleUrl);

    Linking.getInitialURL()
      .then((url) => {
        if (url) {
          handleUrl({ url });
        }
      })
      .catch(() => undefined);

    return () => {
      subscription.remove();
    };
  }, [router]);

  return null;
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
                <ScreenTracker />
                <DeepLinkHandler />
                <UpdateBanner />
                <OfflineBanner />
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
