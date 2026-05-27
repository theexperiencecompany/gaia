"use client";

import posthog from "posthog-js";

/**
 * Centralized analytics module for PostHog integration.
 * Provides type-safe event tracking with consistent naming conventions.
 */

// Event name constants for consistent tracking
export const ANALYTICS_EVENTS = {
  // Auth events
  USER_SESSION_RESUMED: "user:session_resumed",
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
  CHAT_VOICE_MODE_TOGGLED: "chat:voice_mode_toggled",
  CHAT_FILE_UPLOADED: "chat:file_uploaded",
  CHAT_CONVERSATION_DELETED: "chat:conversation_deleted",

  // Chat – interaction detail events
  CHAT_MESSAGE_FEEDBACK: "chat:message_feedback",
  CHAT_SUGGESTION_SHUFFLED: "chat:suggestion_shuffled",
  CHAT_SLASH_COMMAND_SELECTED: "chat:slash_command_selected",
  CHAT_SLASH_COMMAND_CATEGORY_CHANGED: "chat:slash_command_category_changed",
  CHAT_COMPOSER_PLUS_MENU_CLICKED: "chat:composer_plus_menu_clicked",
  CHAT_TOOLS_BUTTON_CLICKED: "chat:tools_button_clicked",
  CHAT_GRID_INTEGRATION_CONNECT_CLICKED:
    "chat:grid_integration_connect_clicked",
  CHAT_CONVERSATION_RENAMED: "chat:conversation_renamed",
  CHAT_CONVERSATION_STARRED: "chat:conversation_starred",
  CHAT_MESSAGE_RETRIED: "chat:message_retried",

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
  TODOS_VIEW_CHANGED: "todos:view_changed",

  // Goal events
  GOALS_CREATED: "goals:created",
  GOALS_DELETED: "goals:deleted",

  // Calendar events
  CALENDAR_EVENT_CREATED: "calendar:event_created",
  CALENDAR_EVENT_DELETED: "calendar:event_deleted",

  // Email events
  EMAIL_OPENED: "email:opened",
  EMAIL_REPLIED: "email:replied",
  EMAIL_COMPOSE_OPENED: "email:compose_opened",
  EMAIL_AI_DRAFT_GENERATED: "email:ai_draft_generated",

  // Settings events
  SETTINGS_PREFERENCES_CHANGED: "settings:preferences_changed",
  SETTINGS_NOTIFICATIONS_TOGGLED: "settings:notifications_toggled",

  // UI/UX events
  UI_SIDEBAR_COLLAPSED: "ui:sidebar_collapsed",
  UI_SIDEBAR_EXPANDED: "ui:sidebar_expanded",

  // Search and filtering
  SEARCH_PERFORMED: "search:performed",
  SEARCH_GLOBAL_OPENED: "search:global_opened",
  SEARCH_RESULT_CLICKED: "search:result_clicked",

  // Pins/Bookmarks events
  PIN_CREATED: "pin:created",
  PIN_DELETED: "pin:deleted",
  PIN_VIEWED: "pin:viewed",

  // Memory events
  MEMORY_CLEARED: "memory:cleared",
  MEMORY_ITEM_DELETED: "memory:item_deleted",

  // Profile events
  PROFILE_LINK_COPIED: "profile:link_copied",

  // Notifications events
  NOTIFICATION_VIEWED: "notification:viewed",
  NOTIFICATION_CLICKED: "notification:clicked",
  NOTIFICATION_DISMISSED: "notification:dismissed",

  // Content/Learning events
  BLOG_ARTICLE_VIEWED: "blog:article_viewed",

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

  // What's new events
  WHATS_NEW_CARD_SHOWN: "whats_new:card_shown",
  WHATS_NEW_CARD_CLICKED: "whats_new:card_clicked",
  WHATS_NEW_CARD_DISMISSED: "whats_new:card_dismissed",
  WHATS_NEW_MODAL_OPENED: "whats_new:modal_opened",
  WHATS_NEW_SLIDE_VIEWED: "whats_new:slide_viewed",
  WHATS_NEW_DOCS_CLICKED: "whats_new:docs_clicked",
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
  first_message_sent?: boolean;
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
  posthog.setPersonProperties(properties);
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
