import { apiService } from "@/lib/api/service";
import type { BrowserTask, SavedBrowserLogin } from "../types";

export const browserApi = {
  listTasks: () =>
    apiService.get<BrowserTask[]>("/browser/tasks?limit=50", { silent: true }),

  deleteTask: (id: string) =>
    apiService.delete(`/browser/tasks/${id}`, {
      successMessage: "Task removed",
      errorMessage: "Could not remove this task",
    }),

  listLogins: () =>
    apiService.get<SavedBrowserLogin[]>("/browser/logins", { silent: true }),

  forgetLogin: (domain: string) =>
    apiService.delete(`/browser/logins/${encodeURIComponent(domain)}`, {
      successMessage: "Login forgotten",
      errorMessage: "Could not forget this login",
    }),

  clearLogins: () =>
    apiService.delete("/browser/logins", {
      successMessage: "All saved logins cleared",
      errorMessage: "Could not clear saved logins",
    }),
};
