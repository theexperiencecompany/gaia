"use client";

import posthog from "posthog-js";

/**
 * Centralized analytics module for PostHog integration.
 * Provides type-safe event tracking with consistent naming conventions.
 */

// Event name constants for consistent tracking
export const ANALYTICS_EVENTS = {
  // Desktop-only and deliberately its own name: Electron IPC (app icon, popup
  // shortcut) that never reaches the API, so no server event exists for it.
  SETTINGS_DESKTOP_PREFERENCE_CHANGED: "settings:desktop_preference_changed",
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
  SUBSCRIPTION_FAILED: "subscription:failed",

  // Chat events
  CHAT_STARTED: "chat:started",
  CHAT_FIRST_MESSAGE_SENT: "chat:first_message_sent",
  CHAT_VOICE_MODE_TOGGLED: "chat:voice_mode_toggled",

  // Chat – interaction detail events
  CHAT_MESSAGE_FEEDBACK: "chat:message_feedback",
  CHAT_SLASH_COMMAND_SELECTED: "chat:slash_command_selected",
  CHAT_SLASH_COMMAND_CATEGORY_CHANGED: "chat:slash_command_category_changed",
  CHAT_COMPOSER_PLUS_MENU_CLICKED: "chat:composer_plus_menu_clicked",
  CHAT_TOOLS_BUTTON_CLICKED: "chat:tools_button_clicked",
  CHAT_GRID_INTEGRATION_CONNECT_CLICKED:
    "chat:grid_integration_connect_clicked",
  CHAT_MESSAGE_RETRIED: "chat:message_retried",

  INTEGRATION_ERROR: "integration:error",

  // Feature discovery events
  FEATURE_DISCOVERED: "feature:discovered",

  // Workflow events
  WORKFLOWS_CREATED: "workflows:created",
  WORKFLOWS_DELETED: "workflows:deleted",
  WORKFLOWS_EXECUTED: "workflows:executed",
  WORKFLOWS_PUBLISHED: "workflows:published",
  WORKFLOWS_UNPUBLISHED: "workflows:unpublished",
  WORKFLOWS_STEPS_REGENERATED: "workflows:steps_regenerated",
  WORKFLOW_CARD_NAVIGATE: "workflow_card:navigate",
  USE_CASES_PROMPT_INSERTED: "use_cases:prompt_inserted",

  TODOS_VIEW_CHANGED: "todos:view_changed",

  // Email events
  EMAIL_OPENED: "email:opened",
  EMAIL_COMPOSE_OPENED: "email:compose_opened",
  EMAIL_AI_DRAFT_GENERATED: "email:ai_draft_generated",

  // UI/UX events
  UI_SIDEBAR_COLLAPSED: "ui:sidebar_collapsed",
  UI_SIDEBAR_EXPANDED: "ui:sidebar_expanded",

  SEARCH_GLOBAL_OPENED: "search:global_opened",
  SEARCH_RESULT_CLICKED: "search:result_clicked",

  // Pins/Bookmarks events
  PIN_CREATED: "pin:created",
  PIN_DELETED: "pin:deleted",
  PIN_VIEWED: "pin:viewed",

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

  // Error events
  ERROR_OCCURRED: "error:occurred",

  // Founder letter events
  FOUNDER_LETTER_SHOWN: "founder_letter:shown",
  FOUNDER_LETTER_OPENED: "founder_letter:opened",
  FOUNDER_LETTER_DISCOUNT_CTA_CLICKED: "founder_letter:discount_cta_clicked",
  FOUNDER_LETTER_CODE_COPIED: "founder_letter:code_copied",
  FOUNDER_LETTER_MEETING_CLICKED: "founder_letter:meeting_clicked",
  FOUNDER_LETTER_DISMISSED: "founder_letter:dismissed",

  // What's new events
  WHATS_NEW_CARD_SHOWN: "whats_new:card_shown",
  WHATS_NEW_CARD_CLICKED: "whats_new:card_clicked",
  WHATS_NEW_CARD_DISMISSED: "whats_new:card_dismissed",
  WHATS_NEW_MODAL_OPENED: "whats_new:modal_opened",
  WHATS_NEW_SLIDE_VIEWED: "whats_new:slide_viewed",
  WHATS_NEW_DOCS_CLICKED: "whats_new:docs_clicked",

  // Voice events
  VOICE_MODE_STARTED: "voice:mode_started",
  VOICE_MODE_STOPPED: "voice:mode_stopped",
  VOICE_TRANSCRIPTION_RECEIVED: "voice:transcription_received",
  WAKE_WORD_DETECTED: "wake_word:detected",

  // Device events
  DEVICE_CONNECTED: "device:connected",
  DEVICE_DISCONNECTED: "device:disconnected",

  // Desktop popup events
  DESKTOP_POPUP_OPENED: "desktop_popup:opened",
  DESKTOP_POPUP_DISMISSED: "desktop_popup:dismissed",

  // Bot events
  BOT_CONNECTED: "bot:connected",
  BOT_DISCONNECTED: "bot:disconnected",

  // Weather events
  WEATHER_QUERIED: "weather:queried",

  SKILL_SEARCHED: "skill:searched",

  // Use case events
  USE_CASE_CLICKED: "use_cases:clicked",

  // Thanks page
  THANKS_PAGE_VIEWED: "thanks:page_viewed",

  // Reddit events
  REDDIT_POST_VIEWED: "reddit:post_viewed",

  // API layer events
  API_REQUEST_FAILED: "api:request_failed",
  API_CHUNK_RECOVERED: "api:chunk_recovered",
  ROUTE_ERROR_SHOWN: "error:route_error_shown",
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
