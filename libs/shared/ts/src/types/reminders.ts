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
