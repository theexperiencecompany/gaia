import posthog from "posthog-js";

/**
 * Centralized analytics module for PostHog integration.
 * Provides type-safe event tracking with consistent naming conventions.
 */

const ANALYTICS_STORAGE_KEY = "gaia_analytics_state";

// Event name constants for consistent tracking
export const ANALYTICS_EVENTS = {
  // Auth events
  USER_LOGGED_IN: "user:logged_in",
  USER_LOGGED_OUT: "user:logged_out",

  // Onboarding events
  ONBOARDING_STARTED: "onboarding:started",
  ONBOARDING_STEP_COMPLETED: "onboarding:step_completed",
  ONBOARDING_COMPLETED: "onboarding:completed",
  ONBOARDING_SKIPPED: "onboarding:skipped",

  // Subscription events
  SUBSCRIPTION_PAGE_VIEWED: "subscription:page_viewed",
  SUBSCRIPTION_PLAN_VIEWED: "subscription:plan_viewed",
  SUBSCRIPTION_CHECKOUT_STARTED: "subscription:checkout_started",
  SUBSCRIPTION_COMPLETED: "subscription:completed",
  SUBSCRIPTION_ACTIVATED: "subscription:activated",
  SUBSCRIPTION_CANCELLED: "subscription:cancelled",
  SUBSCRIPTION_FAILED: "subscription:failed",

  // Chat events
  CHAT_STARTED: "chat:started",
  CHAT_MESSAGE_SENT: "chat:message_sent",
  CHAT_CONVERSATION_CREATED: "chat:conversation_created",
  CHAT_FIRST_MESSAGE_SENT: "chat:first_message_sent",
  CHAT_SUGGESTION_SHUFFLED: "chat:suggestion_shuffled",
  CHAT_SLASH_COMMAND_SELECTED: "chat:slash_command_selected",
  CHAT_SLASH_COMMAND_CATEGORY_CHANGED: "chat:slash_command_category_changed",
  CHAT_COMPOSER_PLUS_MENU_CLICKED: "chat:composer_plus_menu_clicked",
  CHAT_TOOLS_BUTTON_CLICKED: "chat:tools_button_clicked",
  CHAT_GRID_INTEGRATION_CONNECT_CLICKED:
    "chat:grid_integration_connect_clicked",
  CHAT_MESSAGE_FEEDBACK: "chat:message_feedback",

  // Integration events
  INTEGRATION_CONNECTED: "integration:connected",
  INTEGRATION_DISCONNECTED: "integration:disconnected",
  INTEGRATION_ERROR: "integration:error",

  // Feature discovery events
  FEATURE_DISCOVERED: "feature:discovered",
  TOOL_USED: "tool:used",

  // Workflow events
  WORKFLOWS_CREATED: "workflows:created",
  WORKFLOWS_DELETED: "workflows:deleted",
  WORKFLOWS_EXECUTED: "workflows:executed",
  WORKFLOWS_PUBLISHED: "workflows:published",
  WORKFLOWS_UNPUBLISHED: "workflows:unpublished",
  WORKFLOWS_STEPS_REGENERATED: "workflows:steps_regenerated",
  WORKFLOW_CARD_NAVIGATE: "workflow_card:navigate",
  USE_CASES_PROMPT_INSERTED: "use_cases:prompt_inserted",

  // Todo events
  TODOS_CREATED: "todos:created",
  TODOS_UPDATED: "todos:updated",
  TODOS_TOGGLED: "todos:toggled",

  // Goal events
  GOALS_CREATED: "goals:created",

  // Calendar events
  CALENDAR_EVENT_CREATED: "calendar:event_created",
  CALENDAR_EVENT_DELETED: "calendar:event_deleted",

  // Navigation events
  NAVIGATION_SIDEBAR_CLICKED: "navigation:sidebar_clicked",
  NAVIGATION_NAVBAR_LINK_CLICKED: "navigation:navbar_link_clicked",
  NAVIGATION_NAVBAR_DROPDOWN_OPENED: "navigation:navbar_dropdown_opened",
  NAVIGATION_GITHUB_CLICKED: "navigation:github_clicked",
  NAVIGATION_CTA_CLICKED: "navigation:cta_clicked",

  // Pricing events
  PRICING_PLAN_SELECTED: "pricing:plan_selected",

  // CTA events
  CTA_GET_STARTED_CLICKED: "cta:get_started_clicked",

  // Support events
  SUPPORT_FORM_SUBMITTED: "support:form_submitted",

  // Error events
  ERROR_OCCURRED: "error:occurred",
  API_ERROR: "api:error",
} as const;

export type AnalyticsEvent =
  (typeof ANALYTICS_EVENTS)[keyof typeof ANALYTICS_EVENTS];

interface UserProperties {
  email?: string;
  name?: string;
  timezone?: string;
  plan?: string;
  created_at?: string;
  profession?: string;
  onboarding_completed?: boolean;
}

interface EventProperties {
  [key: string]: unknown;
}

/**
 * Identify a user in PostHog.
 * Call this when a user logs in or signs up.
 */
export function identifyUser(
  userId: string,
  properties?: UserProperties,
): void {
  if (!userId) return;

  posthog.identify(userId, {
    ...properties,
    $set_once: {
      first_seen: new Date().toISOString(),
    },
  });
}

/**
 * Reset user identity (call on logout).
 */
export function resetUser(): void {
  posthog.reset();
}

/**
 * Track an analytics event.
 */
export function trackEvent(
  event: AnalyticsEvent | string,
  properties?: EventProperties,
): void {
  posthog.capture(event, {
    ...properties,
    timestamp: new Date().toISOString(),
  });
}

/**
 * Set user properties without tracking an event.
 */
export function setUserProperties(properties: UserProperties): void {
  posthog.people.set(properties);
}

// --- Analytics State Management (persisted in localStorage) ---

interface AnalyticsState {
  hassentFirstMessage: boolean;
  discoveredFeatures: string[];
}

function getAnalyticsState(): AnalyticsState {
  if (typeof window === "undefined") {
    return { hassentFirstMessage: false, discoveredFeatures: [] };
  }
  try {
    const stored = localStorage.getItem(ANALYTICS_STORAGE_KEY);
    return stored
      ? JSON.parse(stored)
      : { hassentFirstMessage: false, discoveredFeatures: [] };
  } catch {
    return { hassentFirstMessage: false, discoveredFeatures: [] };
  }
}

function updateAnalyticsState(updates: Partial<AnalyticsState>): void {
  if (typeof window === "undefined") return;
  try {
    const current = getAnalyticsState();
    localStorage.setItem(
      ANALYTICS_STORAGE_KEY,
      JSON.stringify({ ...current, ...updates }),
    );
  } catch {
    // Silently fail if localStorage is unavailable
  }
}

/**
 * Track when user sends their first-ever message.
 * Only fires once per user (persisted in localStorage).
 */
export function trackFirstMessageIfNeeded(): boolean {
  const state = getAnalyticsState();
  if (state.hassentFirstMessage) return false;

  trackEvent(ANALYTICS_EVENTS.CHAT_FIRST_MESSAGE_SENT, {
    milestone: "first_message",
  });
  setUserProperties({ first_message_sent: true } as UserProperties);
  updateAnalyticsState({ hassentFirstMessage: true });
  return true;
}

/**
 * Track when user creates a new conversation.
 */
export function trackConversationCreated(properties?: {
  conversationId?: string;
  source?: string;
}): void {
  trackEvent(ANALYTICS_EVENTS.CHAT_CONVERSATION_CREATED, properties);
}

/**
 * Track when user discovers/uses a feature for the first time.
 * Only fires once per feature per user.
 */
export function trackFeatureDiscovery(
  featureName: string,
  properties?: EventProperties,
): boolean {
  const state = getAnalyticsState();
  if (state.discoveredFeatures.includes(featureName)) return false;

  trackEvent(ANALYTICS_EVENTS.FEATURE_DISCOVERED, {
    feature: featureName,
    is_first_use: true,
    ...properties,
  });
  updateAnalyticsState({
    discoveredFeatures: [...state.discoveredFeatures, featureName],
  });
  return true;
}

/**
 * Track onboarding progress.
 */
export function trackOnboardingStep(
  step: number,
  stepName: string,
  properties?: EventProperties,
): void {
  trackEvent(ANALYTICS_EVENTS.ONBOARDING_STEP_COMPLETED, {
    step_number: step,
    step_name: stepName,
    ...properties,
  });
}

/**
 * Track onboarding completion.
 */
export function trackOnboardingComplete(properties: {
  profession?: string;
  integrationsConnected?: string[];
  totalSteps: number;
  timeToComplete?: number;
}): void {
  trackEvent(ANALYTICS_EVENTS.ONBOARDING_COMPLETED, properties);
  setUserProperties({
    onboarding_completed: true,
    profession: properties.profession,
  });
}

/**
 * Track subscription events.
 */
export function trackSubscription(
  action: "started" | "completed" | "cancelled" | "failed",
  properties: {
    plan?: string;
    planId?: string;
    amount?: number;
    currency?: string;
    interval?: string;
    previousPlan?: string;
    reason?: string;
  },
): void {
  const eventMap = {
    started: ANALYTICS_EVENTS.SUBSCRIPTION_CHECKOUT_STARTED,
    completed: ANALYTICS_EVENTS.SUBSCRIPTION_COMPLETED,
    cancelled: ANALYTICS_EVENTS.SUBSCRIPTION_CANCELLED,
    failed: ANALYTICS_EVENTS.SUBSCRIPTION_FAILED,
  };

  trackEvent(eventMap[action], properties);

  if (action === "completed" && properties.plan) {
    setUserProperties({ plan: properties.plan });
  }
}

/**
 * Track integration connection events.
 */
export function trackIntegration(
  action: "connected" | "disconnected" | "error",
  integrationName: string,
  properties?: EventProperties,
): void {
  const eventMap = {
    connected: ANALYTICS_EVENTS.INTEGRATION_CONNECTED,
    disconnected: ANALYTICS_EVENTS.INTEGRATION_DISCONNECTED,
    error: ANALYTICS_EVENTS.INTEGRATION_ERROR,
  };

  trackEvent(eventMap[action], {
    integration: integrationName,
    ...properties,
  });

  // Track first-time integration connection as feature discovery
  if (action === "connected") {
    trackFeatureDiscovery(`integration_${integrationName}`, {
      integration: integrationName,
    });
  }
}

/**
 * Track errors for debugging and monitoring.
 */
export function trackError(
  errorType: string,
  error: Error | string,
  properties?: EventProperties,
): void {
  trackEvent(ANALYTICS_EVENTS.ERROR_OCCURRED, {
    error_type: errorType,
    error_message: error instanceof Error ? error.message : error,
    error_stack: error instanceof Error ? error.stack : undefined,
    ...properties,
  });
}

/**
 * Create a group (for team/organization tracking).
 */
export function setGroup(
  groupType: string,
  groupKey: string,
  properties?: Record<string, unknown>,
): void {
  posthog.group(groupType, groupKey, properties);
}

/**
 * Opt user out of tracking.
 */
export function optOut(): void {
  posthog.opt_out_capturing();
}

/**
 * Opt user back into tracking.
 */
export function optIn(): void {
  posthog.opt_in_capturing();
}

/**
 * Check if capturing is active.
 */
export function isCapturingEnabled(): boolean {
  return !posthog.has_opted_out_capturing();
}

// Re-export posthog for advanced usage
export { posthog };
