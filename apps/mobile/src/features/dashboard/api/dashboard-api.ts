import { buildQueryString, normalizeListResponse } from "@gaia/shared/api";
import type { Reminder } from "@gaia/shared/types";
import type { Conversation } from "@/features/chat/types";
import type { InAppNotificationsListResponse } from "@/features/notifications/types/inapp-notification-types";
import type { Todo, TodoListResponse } from "@/features/todos/types/todo-types";
import type { WorkflowListResponse } from "@/features/workflows/types/workflow-types";
import { apiService } from "@/lib/api";

interface ApiConversation {
  _id: string;
  user_id: string;
  conversation_id: string;
  description: string;
  is_system_generated: boolean;
  system_purpose: string | null;
  is_unread?: boolean;
  createdAt: string;
  updatedAt?: string;
}

interface ConversationsResponse {
  conversations: ApiConversation[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

interface RemindersListResponse {
  reminders: Reminder[];
  total: number;
}

function normalizeConversation(apiConv: ApiConversation): Conversation {
  return {
    id: apiConv.conversation_id,
    title: apiConv.description || "Untitled conversation",
    created_at: apiConv.createdAt,
    updated_at: apiConv.updatedAt || apiConv.createdAt,
    is_unread: apiConv.is_unread,
  };
}

export const dashboardApi = {
  getTodayTodos: async (): Promise<Todo[]> => {
    const response = await apiService.get<TodoListResponse | Todo[]>(
      `/todos${buildQueryString({ due_today: true, completed: false, limit: 3 })}`,
    );
    return normalizeListResponse(response);
  },

  getRecentConversations: async (): Promise<Conversation[]> => {
    const data = await apiService.get<ConversationsResponse>(
      "/conversations?page=1&limit=3",
    );
    return (data.conversations || []).map(normalizeConversation);
  },

  getUnreadNotificationsCount: async (): Promise<number> => {
    const response = await apiService.get<InAppNotificationsListResponse>(
      "/notifications?status=delivered&limit=1",
    );
    return response.total ?? 0;
  },

  getUpcomingReminders: async (): Promise<Reminder[]> => {
    const response = await apiService.get<RemindersListResponse | Reminder[]>(
      "/reminders?limit=2",
    );
    if (Array.isArray(response)) {
      return response;
    }
    return response.reminders ?? [];
  },

  getActiveWorkflowsCount: async (): Promise<number> => {
    const response = await apiService.get<WorkflowListResponse>(
      `/workflows${buildQueryString({ activated: true })}`,
    );
    return response.total_count ?? 0;
  },
};
