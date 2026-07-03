import { apiService } from "@/lib/api/service";

/**
 * Web-specific todo action endpoints (approve / dismiss / handoff a
 * GAIA-assigned todo). Kept separate from `todoApi.ts` — that file wraps the
 * cross-platform `TodoApiClient` shared with mobile via `@shared/todos`,
 * while these actions are web-only (`channel: "web"`) and not part of the
 * shared contract.
 */

export type TodoActionChannel = "web";

export interface ApproveTodoResponse {
  success: boolean;
  todo_id: string;
  execution_status: "queued";
}

export interface DismissTodoResponse {
  success: boolean;
  todo_id: string;
}

export interface HandoffTodoResponse {
  success: boolean;
  todo_id: string;
}

/** Shape of the 402 body returned when the user is out of GAIA execution quota. */
export interface GaiaExecutionQuotaError {
  error: "gaia_execution_quota";
  todo_id: string;
  pitch: string;
  plan_required: string;
  reset_time: string;
}

export function approveTodo(todoId: string): Promise<ApproveTodoResponse> {
  return apiService.post<ApproveTodoResponse>(
    `/todos/${todoId}/approve`,
    { channel: "web" satisfies TodoActionChannel },
    { silent: true },
  );
}

export function dismissTodo(
  todoId: string,
  reason?: string,
): Promise<DismissTodoResponse> {
  return apiService.post<DismissTodoResponse>(
    `/todos/${todoId}/dismiss`,
    { reason, channel: "web" satisfies TodoActionChannel },
    { silent: true },
  );
}

export function handoffTodo(todoId: string): Promise<HandoffTodoResponse> {
  return apiService.post<HandoffTodoResponse>(
    `/todos/${todoId}/handoff`,
    {},
    { silent: true },
  );
}
