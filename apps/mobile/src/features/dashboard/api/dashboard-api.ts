import { buildQueryString, normalizeListResponse } from "@gaia/shared/api";
import type {
  ConversationListResponse,
  ConversationSummary,
} from "@gaia/shared/api/generated";
import type { Reminder } from "@gaia/shared/types";
import type { Conversation } from "@/features/chat/types";
import type { InAppNotificationsListResponse } from "@/features/notifications/types/inapp-notification-types";
import type { Todo, TodoListResponse } from "@/features/todos/types/todo-types";
import type { WorkflowListResponse } from "@/features/workflows/types/workflow-types";
import { apiService } from "@/lib/api";

interface RemindersListResponse {
  reminders: Reminder[];
  total: number;
}

const EPOCH_ISO = new Date(0).toISOString();

function normalizeConversation(apiConv: ConversationSummary): Conversation {
  return {
    id: apiConv.conversation_id,
    title: apiConv.description || "Untitled conversation",
    // An undated row sorts as the epoch, as the web list does.
    created_at: apiConv.createdAt ?? EPOCH_ISO,
    updated_at: apiConv.updatedAt ?? apiConv.createdAt ?? EPOCH_ISO,
    is_unread: apiConv.is_unread ?? undefined,
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
    const data = await apiService.get<ConversationListResponse>(
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
    const response = await apiService.get<WorkflowListResponse>("/workflows");
    return response.workflows.filter((workflow) => workflow.activated).length;
  },
};
