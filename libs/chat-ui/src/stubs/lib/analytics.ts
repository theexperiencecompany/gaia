/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */

// Event name constants — these are pure data and copied verbatim from source.
export const ANALYTICS_EVENTS = {
  USER_SESSION_RESUMED: "user:session_resumed",
  USER_LOGGED_IN: "user:logged_in",
  USER_LOGGED_OUT: "user:logged_out",
  ONBOARDING_STARTED: "onboarding:started",
  ONBOARDING_STEP_COMPLETED: "onboarding:step_completed",
  ONBOARDING_COMPLETED: "onboarding:completed",
  ONBOARDING_SKIPPED: "onboarding:skipped",
  SUBSCRIPTION_PAGE_VIEWED: "subscription:page_viewed",
  SUBSCRIPTION_PLAN_VIEWED: "subscription:plan_viewed",
  SUBSCRIPTION_CHECKOUT_STARTED: "subscription:checkout_started",
  SUBSCRIPTION_COMPLETED: "subscription:completed",
  SUBSCRIPTION_ACTIVATED: "subscription:activated",
  SUBSCRIPTION_CANCELLED: "subscription:cancelled",
  SUBSCRIPTION_FAILED: "subscription:failed",
  CHAT_STARTED: "chat:started",
  CHAT_MESSAGE_SENT: "chat:message_sent",
  CHAT_CONVERSATION_CREATED: "chat:conversation_created",
  CHAT_FIRST_MESSAGE_SENT: "chat:first_message_sent",
  CHAT_VOICE_MODE_TOGGLED: "chat:voice_mode_toggled",
  CHAT_FILE_UPLOADED: "chat:file_uploaded",
  CHAT_CONVERSATION_DELETED: "chat:conversation_deleted",
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
  INTEGRATION_CONNECTED: "integration:connected",
  INTEGRATION_DISCONNECTED: "integration:disconnected",
  INTEGRATION_ERROR: "integration:error",
  FEATURE_DISCOVERED: "feature:discovered",
  TOOL_USED: "tool:used",
  WORKFLOWS_CREATED: "workflows:created",
  WORKFLOWS_DELETED: "workflows:deleted",
  WORKFLOWS_EXECUTED: "workflows:executed",
  WORKFLOWS_PUBLISHED: "workflows:published",
  WORKFLOWS_UNPUBLISHED: "workflows:unpublished",
  WORKFLOWS_STEPS_REGENERATED: "workflows:steps_regenerated",
  WORKFLOW_CARD_NAVIGATE: "workflow_card:navigate",
  USE_CASES_PROMPT_INSERTED: "use_cases:prompt_inserted",
  TODOS_CREATED: "todos:created",
  TODOS_UPDATED: "todos:updated",
  TODOS_TOGGLED: "todos:toggled",
  TODOS_VIEW_CHANGED: "todos:view_changed",
  GOALS_CREATED: "goals:created",
  GOALS_DELETED: "goals:deleted",
  CALENDAR_EVENT_CREATED: "calendar:event_created",
  CALENDAR_EVENT_DELETED: "calendar:event_deleted",
  EMAIL_OPENED: "email:opened",
  EMAIL_REPLIED: "email:replied",
  EMAIL_COMPOSE_OPENED: "email:compose_opened",
  EMAIL_AI_DRAFT_GENERATED: "email:ai_draft_generated",
  SETTINGS_PREFERENCES_CHANGED: "settings:preferences_changed",
  SETTINGS_NOTIFICATIONS_TOGGLED: "settings:notifications_toggled",
  UI_SIDEBAR_COLLAPSED: "ui:sidebar_collapsed",
  UI_SIDEBAR_EXPANDED: "ui:sidebar_expanded",
  SEARCH_PERFORMED: "search:performed",
  SEARCH_GLOBAL_OPENED: "search:global_opened",
  SEARCH_RESULT_CLICKED: "search:result_clicked",
  PIN_CREATED: "pin:created",
  PIN_DELETED: "pin:deleted",
  PIN_VIEWED: "pin:viewed",
  MEMORY_CLEARED: "memory:cleared",
  MEMORY_ITEM_DELETED: "memory:item_deleted",
  PROFILE_LINK_COPIED: "profile:link_copied",
  NOTIFICATION_VIEWED: "notification:viewed",
  NOTIFICATION_CLICKED: "notification:clicked",
  NOTIFICATION_DISMISSED: "notification:dismissed",
  BLOG_ARTICLE_VIEWED: "blog:article_viewed",
  NAVIGATION_SIDEBAR_CLICKED: "navigation:sidebar_clicked",
  NAVIGATION_NAVBAR_LINK_CLICKED: "navigation:navbar_link_clicked",
  NAVIGATION_NAVBAR_DROPDOWN_OPENED: "navigation:navbar_dropdown_opened",
  NAVIGATION_GITHUB_CLICKED: "navigation:github_clicked",
  NAVIGATION_CTA_CLICKED: "navigation:cta_clicked",
  PRICING_PLAN_SELECTED: "pricing:plan_selected",
  CTA_GET_STARTED_CLICKED: "cta:get_started_clicked",
  SUPPORT_FORM_SUBMITTED: "support:form_submitted",
  ERROR_OCCURRED: "error:occurred",
  API_ERROR: "api:error",
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

export function identifyUser(
  _userId: string,
  _properties?: UserProperties,
): void {}

export function resetUser(): void {}

export function trackEvent(
  _event: AnalyticsEvent | string,
  _properties?: EventProperties,
): void {}

export function setUserProperties(_properties: UserProperties): void {}

export function trackFirstMessageIfNeeded(): boolean {
  return false;
}

export function trackConversationCreated(_properties?: {
  conversationId?: string;
  source?: string;
}): void {}

export function trackFeatureDiscovery(
  _featureName: string,
  _properties?: EventProperties,
): boolean {
  return false;
}

export function trackOnboardingStep(
  _step: number,
  _stepName: string,
  _properties?: EventProperties,
): void {}

export function trackOnboardingComplete(_properties: {
  profession?: string;
  integrationsConnected?: string[];
  totalSteps: number;
  timeToComplete?: number;
}): void {}

export function trackSubscription(
  _action: "started" | "completed" | "cancelled" | "failed",
  _properties: {
    plan?: string;
    planId?: string;
    amount?: number;
    currency?: string;
    interval?: string;
    previousPlan?: string;
    reason?: string;
  },
): void {}

export function trackIntegration(
  _action: "connected" | "disconnected" | "error",
  _integrationName: string,
  _properties?: EventProperties,
): void {}

export function trackError(
  _errorType: string,
  _error: Error | string,
  _properties?: EventProperties,
): void {}

// posthog stub — minimal shape for any direct callers (e.g. sendBeacon transport)
export const posthog = {
  capture: (_event: string, _props?: Record<string, unknown>) => {},
  identify: (_id: string, _props?: Record<string, unknown>) => {},
  reset: () => {},
  setPersonProperties: (_props: Record<string, unknown>) => {},
};
