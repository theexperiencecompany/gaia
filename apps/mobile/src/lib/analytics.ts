import AsyncStorage from "@react-native-async-storage/async-storage";

const ANALYTICS_STORAGE_KEY = "gaia_analytics_state";

export const ANALYTICS_EVENTS = {
  // Auth events
  USER_LOGGED_IN: "user:logged_in",
  USER_LOGGED_OUT: "user:logged_out",

  // Onboarding events
  ONBOARDING_STARTED: "onboarding:started",
  ONBOARDING_STEP_COMPLETED: "onboarding:step_completed",
  ONBOARDING_COMPLETED: "onboarding:completed",
  ONBOARDING_SKIPPED: "onboarding:skipped",

  // Chat events
  CHAT_STARTED: "chat:started",
  CHAT_MESSAGE_SENT: "chat:message_sent",
  CHAT_CONVERSATION_CREATED: "chat:conversation_created",
  CHAT_FIRST_MESSAGE_SENT: "chat:first_message_sent",

  // Integration events
  INTEGRATION_CONNECTED: "integration:connected",
  INTEGRATION_DISCONNECTED: "integration:disconnected",
  INTEGRATION_ERROR: "integration:error",

  // Workflow events
  WORKFLOWS_CREATED: "workflows:created",
  WORKFLOWS_DELETED: "workflows:deleted",
  WORKFLOWS_EXECUTED: "workflows:executed",

  // Todo events
  TODOS_CREATED: "todos:created",
  TODOS_UPDATED: "todos:updated",
  TODOS_TOGGLED: "todos:toggled",

  // Navigation events
  SCREEN_VIEWED: "screen:viewed",

  // Support events
  SUPPORT_FORM_SUBMITTED: "support:form_submitted",

  // Error events
  ERROR_OCCURRED: "error:occurred",
} as const;

export type AnalyticsEvent =
  (typeof ANALYTICS_EVENTS)[keyof typeof ANALYTICS_EVENTS];

interface EventProperties {
  [key: string]: unknown;
}

interface UserTraits {
  email?: string;
  name?: string;
  timezone?: string;
  plan?: string;
  created_at?: string;
}

// PostHog client placeholder — replace with posthog-react-native when installed.
// The interface matches PostHog's API so the swap is a one-liner.
interface PostHogClient {
  capture(event: string, properties?: Record<string, unknown>): void;
  identify(distinctId: string, properties?: Record<string, unknown>): void;
  reset(): void;
  screen(name: string, properties?: Record<string, unknown>): void;
}

function createNoopClient(): PostHogClient {
  return {
    capture: () => undefined,
    identify: () => undefined,
    reset: () => undefined,
    screen: () => undefined,
  };
}

let posthogClient: PostHogClient = createNoopClient();

export function initAnalytics(client: PostHogClient): void {
  posthogClient = client;
}

export function trackEvent(
  name: AnalyticsEvent | string,
  properties?: EventProperties,
): void {
  posthogClient.capture(name, {
    ...properties,
    timestamp: new Date().toISOString(),
  });
}

export function identifyUser(userId: string, traits?: UserTraits): void {
  if (!userId) return;
  posthogClient.identify(userId, {
    ...traits,
    $set_once: { first_seen: new Date().toISOString() },
  });
}

export function resetUser(): void {
  posthogClient.reset();
}

export function trackScreen(name: string, properties?: EventProperties): void {
  posthogClient.screen(name, properties);
  posthogClient.capture(ANALYTICS_EVENTS.SCREEN_VIEWED, {
    screen_name: name,
    ...properties,
  });
}

// ─── Persisted state helpers ──────────────────────────────────────────────────

interface AnalyticsState {
  hasSentFirstMessage: boolean;
}

async function getAnalyticsState(): Promise<AnalyticsState> {
  try {
    const stored = await AsyncStorage.getItem(ANALYTICS_STORAGE_KEY);
    return stored
      ? (JSON.parse(stored) as AnalyticsState)
      : { hasSentFirstMessage: false };
  } catch {
    return { hasSentFirstMessage: false };
  }
}

async function updateAnalyticsState(
  updates: Partial<AnalyticsState>,
): Promise<void> {
  try {
    const current = await getAnalyticsState();
    await AsyncStorage.setItem(
      ANALYTICS_STORAGE_KEY,
      JSON.stringify({ ...current, ...updates }),
    );
  } catch {
    // Silently fail
  }
}

export async function trackFirstMessageIfNeeded(): Promise<boolean> {
  const state = await getAnalyticsState();
  if (state.hasSentFirstMessage) return false;

  trackEvent(ANALYTICS_EVENTS.CHAT_FIRST_MESSAGE_SENT, {
    milestone: "first_message",
  });
  await updateAnalyticsState({ hasSentFirstMessage: true });
  return true;
}
