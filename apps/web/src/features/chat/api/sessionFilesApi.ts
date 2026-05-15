import { apiauth } from "@/lib/api/client";
import { apiService } from "@/lib/api/service";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(
  /\/$/,
  "",
);

export interface ArtifactInfo {
  path: string;
  size_bytes: number;
  mtime: number;
  content_type: string | null;
}

function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

/**
 * Session workspace files. `.user-visible/` artifacts (agent output) and
 * `user-uploaded/` attachments are served by the backend `/sessions` router.
 * `listVisible` is also the tab-focus reconcile path for missed live events.
 */
export const sessionFilesApi = {
  listVisible: (conversationId: string) =>
    apiService.get<ArtifactInfo[]>(`/sessions/${conversationId}/visible`, {
      silent: true,
    }),

  listUploads: (conversationId: string) =>
    apiService.get<ArtifactInfo[]>(`/sessions/${conversationId}/uploads`, {
      silent: true,
    }),

  visibleUrl: (conversationId: string, path: string) =>
    `${API_BASE}/sessions/${conversationId}/visible/${encodePath(path)}`,

  uploadUrl: (conversationId: string, path: string) =>
    `${API_BASE}/sessions/${conversationId}/uploads/${encodePath(path)}`,

  fetchVisible: async (
    conversationId: string,
    path: string,
  ): Promise<string> => {
    const res = await apiauth.get<string>(
      `/sessions/${conversationId}/visible/${encodePath(path)}`,
      { responseType: "text" },
    );
    return res.data;
  },

  pin: (conversationId: string, path: string, targetName?: string) =>
    apiService.post(`/sessions/${conversationId}/pin`, {
      path,
      target_name: targetName,
    }),
};
