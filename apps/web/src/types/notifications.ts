/** Mirrors the backend `NotificationSourceEnum` (apps/api/app/models/notification/notification_models.py). */
export enum NotificationSource {
  AI_EMAIL_DRAFT = "ai_email_draft",
  AI_CALENDAR_EVENT = "ai_calendar_event",
  AI_TODO_SUGGESTION = "ai_todo_suggestion",
  AI_REMINDER = "ai_reminder",
  AI_TODO_ADDED = "ai_todo_added",
  AI_AGENT = "ai_agent",
  EMAIL_TRIGGER = "email_trigger",
  BACKGROUND_JOB = "background_job",
  WORKFLOW_COMPLETED = "workflow_completed",
  WORKFLOW_FAILED = "workflow_failed",
  SYSTEM_WORKFLOWS_PROVISIONED = "system_workflows_provisioned",
  USAGE_LIMIT = "usage_limit",
  INTEGRATION_EXPIRED = "integration_expired",
}
