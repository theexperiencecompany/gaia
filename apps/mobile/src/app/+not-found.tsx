import { useRouter } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";

/**
 * Catch-all route. Backend OAuth callbacks and deep links sometimes redirect
 * to a path that no longer exists on mobile (e.g. WorkOS-side redirect lands
 * on a route the mobile app doesn't define). Instead of showing the default
 * Expo Router 404 ("unmatched route") page, silently redirect to the home
 * screen — the auth/session state has already been handled by the time we
 * get here.
 */
export default function NotFound() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/");
  }, [router]);

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: "#111111",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <ActivityIndicator color="#00bbff" />
    </View>
  );
}
