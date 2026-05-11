interface NotificationAction {
  label: string;
  variant?: "default" | "secondary" | "outline" | "ghost";
  actionId?: string; // ID of the backend action to execute
}

export enum NotificationSource {
  AI_EMAIL_DRAFT = "ai_email_draft",
  AI_CALENDAR_EVENT = "ai_calendar_event",
  AI_TODO_SUGGESTION = "ai_todo_suggestion",
  AI_REMINDER = "ai_reminder",
  AI_TODO_ADDED = "ai_todo_added",
  EMAIL_TRIGGER = "email_trigger",
  BACKGROUND_JOB = "background_job",
}

export interface Notification {
  source: NotificationSource;
  id: string;
  title: string;
  description: string;
  timestamp: string;
  timeGroup: "Today" | "Yesterday" | "Earlier";
  actions: {
    primary?: NotificationAction;
    secondary?: NotificationAction;
  };
}

export type GroupedNotifications = Record<string, Notification[]>;
