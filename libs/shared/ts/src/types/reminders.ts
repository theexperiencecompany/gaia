export type ReminderStatus = "active" | "paused" | "completed";

export interface Reminder {
  id: string;
  title: string;
  description?: string;
  cronExpression: string;
  timezone: string;
  status: ReminderStatus;
  nextRunAt?: string;
  lastRunAt?: string;
  createdAt: string;
  userId: string;
}

export interface ReminderCreate {
  title: string;
  description?: string;
  cronExpression: string;
  timezone?: string;
}

export interface ReminderUpdate {
  title?: string;
  description?: string;
  cronExpression?: string;
  timezone?: string;
  status?: ReminderStatus;
}

export interface CronValidationResult {
  valid: boolean;
  nextRuns?: string[];
  error?: string;
}
