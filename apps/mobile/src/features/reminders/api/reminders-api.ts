import { apiService } from "@/lib/api";

export type ReminderStatus = "active" | "paused";

export interface Reminder {
  id: string;
  title: string;
  description?: string;
  cron_expression: string;
  timezone: string;
  status: ReminderStatus;
  next_run?: string;
  created_at: string;
  updated_at: string;
}

export interface ReminderCreate {
  title: string;
  description?: string;
  cronExpression: string;
  timezone: string;
}

export interface ReminderUpdate {
  title?: string;
  description?: string;
  cronExpression?: string;
  timezone?: string;
}

export interface CronValidationResult {
  valid: boolean;
  error?: string;
  description?: string;
}

export const remindersApi = {
  getReminders: (): Promise<Reminder[]> => {
    return apiService.get<Reminder[]>("/reminders");
  },

  createReminder: (data: ReminderCreate): Promise<Reminder> => {
    return apiService.post<Reminder>("/reminders", {
      title: data.title,
      description: data.description,
      cron_expression: data.cronExpression,
      timezone: data.timezone,
    });
  },

  updateReminder: (id: string, data: ReminderUpdate): Promise<Reminder> => {
    return apiService.put<Reminder>(`/reminders/${id}`, {
      ...(data.title !== undefined && { title: data.title }),
      ...(data.description !== undefined && {
        description: data.description,
      }),
      ...(data.cronExpression !== undefined && {
        cron_expression: data.cronExpression,
      }),
      ...(data.timezone !== undefined && { timezone: data.timezone }),
    });
  },

  deleteReminder: (id: string): Promise<void> => {
    return apiService.delete<void>(`/reminders/${id}`);
  },

  pauseReminder: (id: string): Promise<Reminder> => {
    return apiService.post<Reminder>(`/reminders/${id}/pause`);
  },

  resumeReminder: (id: string): Promise<Reminder> => {
    return apiService.post<Reminder>(`/reminders/${id}/resume`);
  },

  validateCron: (expression: string): Promise<CronValidationResult> => {
    return apiService.post<CronValidationResult>("/reminders/validate-cron", {
      expression,
    });
  },
};
