import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import * as SecureStore from "expo-secure-store";
import { useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import { notificationsApi } from "../api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldPlaySound: true,
    shouldSetBadge: true,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

interface UseNotificationsReturn {
  expoPushToken: string | null;
  notification: Notifications.Notification | null;
  error: string | null;
  isRegistered: boolean;
  isLoading: boolean;
}

export function useNotifications(): UseNotificationsReturn {
  const [expoPushToken, setExpoPushToken] = useState<string | null>(null);
  const [notification, setNotification] =
    useState<Notifications.Notification | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRegistered, setIsRegistered] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const notificationListener = useRef<Notifications.Subscription | null>(null);
  const responseListener = useRef<Notifications.Subscription | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function setupNotifications() {
      try {
        setIsLoading(true);

        // Setup Android notification channel
        if (Platform.OS === "android") {
          await Notifications.setNotificationChannelAsync("gaia_channel", {
            name: "GAIA Notifications",
            importance: Notifications.AndroidImportance.MAX,
            vibrationPattern: [0, 250, 250, 250],
            lightColor: "#00bbff",
            sound: "uwu",
            enableVibrate: true,
            enableLights: true,
          });
        }

        // Check if physical device
        if (!Device.isDevice) {
          const errorMsg = "Push notifications require a physical device";
          setError(errorMsg);
          setIsLoading(false);
          return;
        }

        // Request permissions
        const { status: existingStatus } =
          await Notifications.getPermissionsAsync();
        let finalStatus = existingStatus;

        if (existingStatus !== "granted") {
          const { status } = await Notifications.requestPermissionsAsync();
          finalStatus = status;
        }

        if (finalStatus !== "granted") {
          const errorMsg = "Permission not granted for push notifications";
          setError(errorMsg);
          setIsLoading(false);
          return;
        }

        // Get Expo push token
        const projectId =
          Constants?.expoConfig?.extra?.eas?.projectId ??
          Constants?.easConfig?.projectId;

        if (!projectId) {
          const errorMsg = "Project ID not found in app config";
          setError(errorMsg);
          setIsLoading(false);
          return;
        }

        const pushTokenData = await Notifications.getExpoPushTokenAsync({
          projectId,
        });

        const token = pushTokenData.data;

        if (!isMounted) return;

        setExpoPushToken(token);

        const storedToken = await SecureStore.getItemAsync("expo_push_token");
        const isAlreadyRegistered =
          storedToken === token &&
          (await SecureStore.getItemAsync("expo_push_token_registered")) ===
            "true";

        if (isAlreadyRegistered) {
          setIsRegistered(true);
          setError(null);
        } else {
          // Store token and register with backend
          await SecureStore.setItemAsync("expo_push_token", token);

          try {
            await notificationsApi.registerDeviceToken({
              token,
              platform: Platform.OS as "ios" | "android",
              device_id: Device.deviceName || undefined,
            });
            await SecureStore.setItemAsync(
              "expo_push_token_registered",
              "true",
            );
            setIsRegistered(true);
            setError(null);
          } catch (_backendError) {
            await SecureStore.deleteItemAsync("expo_push_token_registered");
            setIsRegistered(false);
            setError("Failed to register device for push notifications");
          }
        }
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : String(err);
        if (isMounted) {
          setError(errorMsg);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    setupNotifications();

    // Setup listeners
    notificationListener.current =
      Notifications.addNotificationReceivedListener((receivedNotification) => {
        setNotification(receivedNotification);
      });

    responseListener.current =
      Notifications.addNotificationResponseReceivedListener((response) => {
        const data = response.notification.request.content.data;
        if (data) {
        }
      });

    return () => {
      isMounted = false;
      notificationListener.current?.remove();
      responseListener.current?.remove();
    };
  }, []);

  return {
    expoPushToken,
    notification,
    error,
    isRegistered,
    isLoading,
  };
}
