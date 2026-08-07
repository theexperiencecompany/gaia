import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";
import { useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import { chatApi } from "@/features/chat/api/chat-api";
import { notificationsApi } from "@/features/notifications/api/notifications-api";

// Check if running in Expo Go
const isExpoGo = Constants.appOwnership === "expo";

// Only setup notification handler if not in Expo Go on Android
if (!(isExpoGo && Platform.OS === "android")) {
  try {
    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldPlaySound: true,
        shouldSetBadge: true,
        shouldShowBanner: true,
        shouldShowList: true,
      }),
    });
  } catch (e) {
    // Silently fail in Expo Go but log for debugging
    console.warn(
      "[Notifications] Handler setup failed (expected in Expo Go):",
      e,
    );
  }
}

interface UseNotificationsReturn {
  expoPushToken: string | null;
  notification: Notifications.Notification | null;
  error: string | null;
  isRegistered: boolean;
  isLoading: boolean;
}

function resolveNotificationRoute(
  data: Record<string, unknown>,
): string | null {
  const type = typeof data.type === "string" ? data.type.toLowerCase() : "";
  const source =
    typeof data.source === "string" ? data.source.toLowerCase() : "";
  const key = `${source} ${type}`;

  if (key.includes("todo") || key.includes("task")) {
    return "/(app)/(tabs)/todos";
  }

  if (key.includes("workflow") || key.includes("automation")) {
    const workflowId =
      typeof data.workflow_id === "string" ? data.workflow_id : null;
    return workflowId ? `/(app)/workflows/${workflowId}` : "/(app)/(tabs)";
  }

  if (
    key.includes("approval") ||
    key.includes("chat") ||
    key.includes("conversation") ||
    key.includes("message")
  ) {
    // Land in chat where the approval card is actionable — the fully-killed-app
    // case only delivers a plain tap, so tap-through must always be actionable.
    return "/(app)/(tabs)";
  }

  return null;
}

type PushTokenResult =
  | { token: string; error?: undefined }
  | { token?: undefined; error: string };

/** Run device/permission/config checks and fetch the Expo push token. */
async function acquireExpoPushToken(): Promise<PushTokenResult> {
  if (!Device.isDevice) {
    return { error: "Push notifications require a physical device" };
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;
  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }
  if (finalStatus !== "granted") {
    return { error: "Permission not granted for push notifications" };
  }

  const projectId =
    Constants?.expoConfig?.extra?.eas?.projectId ??
    Constants?.easConfig?.projectId;
  if (!projectId) {
    return { error: "Project ID not found in app config" };
  }

  const pushTokenData = await Notifications.getExpoPushTokenAsync({
    projectId,
  });
  return { token: pushTokenData.data };
}

async function ensureAndroidChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
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

async function isTokenAlreadyRegistered(token: string): Promise<boolean> {
  const storedToken = await SecureStore.getItemAsync("expo_push_token");
  return (
    storedToken === token &&
    (await SecureStore.getItemAsync("expo_push_token_registered")) === "true"
  );
}

/** Persist and register the token with the backend; returns success. */
async function registerTokenWithBackend(token: string): Promise<boolean> {
  await SecureStore.setItemAsync("expo_push_token", token);
  try {
    await notificationsApi.registerDeviceToken({
      token,
      platform: Platform.OS as "ios" | "android",
      device_id: Device.deviceName || undefined,
    });
    await SecureStore.setItemAsync("expo_push_token_registered", "true");
    return true;
  } catch (_backendError) {
    await SecureStore.deleteItemAsync("expo_push_token_registered");
    return false;
  }
}

/** Determine registration state for a token, registering it if needed. */
async function resolveRegistration(
  token: string,
): Promise<{ registered: boolean; error: string | null }> {
  if (await isTokenAlreadyRegistered(token)) {
    return { registered: true, error: null };
  }
  const registered = await registerTokenWithBackend(token);
  return {
    registered,
    error: registered
      ? null
      : "Failed to register device for push notifications",
  };
}

export function useNotifications(): UseNotificationsReturn {
  const router = useRouter();
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

        // Skip push notification setup in Expo Go on Android (not supported since SDK 53)
        if (isExpoGo && Platform.OS === "android") {
          setError(
            "Push notifications are not supported in Expo Go. Use a development build.",
          );
          setIsLoading(false);
          return;
        }

        // Setup Android notification channel
        await ensureAndroidChannel();

        // Interactive HIL approval actions — approve/deny straight from the
        // notification (iOS action buttons; Android shows them where supported).
        await Notifications.setNotificationCategoryAsync("hil_approval", [
          { identifier: "approve", buttonTitle: "Approve" },
          {
            identifier: "deny",
            buttonTitle: "Deny",
            options: { isDestructive: true },
          },
        ]);

        const tokenResult = await acquireExpoPushToken();
        if (tokenResult.error !== undefined) {
          setError(tokenResult.error);
          setIsLoading(false);
          return;
        }

        const token = tokenResult.token;
        if (!isMounted) return;

        setExpoPushToken(token);

        const { registered, error: regError } =
          await resolveRegistration(token);
        setIsRegistered(registered);
        setError(regError);
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

    // Setup listeners (skip in Expo Go on Android)
    if (!(isExpoGo && Platform.OS === "android")) {
      notificationListener.current =
        Notifications.addNotificationReceivedListener(
          (receivedNotification) => {
            setNotification(receivedNotification);
          },
        );

      responseListener.current =
        Notifications.addNotificationResponseReceivedListener((response) => {
          const data = response.notification.request.content.data as Record<
            string,
            unknown
          >;
          const action = response.actionIdentifier;
          const approvalId =
            typeof data.approval_id === "string" ? data.approval_id : null;

          // Approve/Deny action button: relay the decision without opening the
          // app. A 410 (already resolved) is swallowed by postApprovalDecision;
          // false means the submit genuinely failed — tell the user, or they'll
          // believe they approved an action that never ran.
          if (
            data.type === "hil_approval" &&
            approvalId &&
            (action === "approve" || action === "deny")
          ) {
            void chatApi
              .postApprovalDecision(approvalId, { decision: action })
              .then((ok) => {
                if (!ok) {
                  void Notifications.scheduleNotificationAsync({
                    content: {
                      title: "Approval not sent",
                      body: "Your decision didn't go through — open GAIA to retry.",
                    },
                    trigger: null,
                  });
                }
              });
            return;
          }

          const route = resolveNotificationRoute(data);
          if (route) {
            router.push(route as never);
          }
        });
    }

    return () => {
      isMounted = false;
      notificationListener.current?.remove();
      responseListener.current?.remove();
    };
  }, [router]);

  return {
    expoPushToken,
    notification,
    error,
    isRegistered,
    isLoading,
  };
}
