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
 * Rewrite bot-emitted artifact paths (./artifacts/foo, /artifacts/foo,
 * artifacts/foo) to the auth-gated backend URL for the current conversation.
 * Returns the original src for anything that doesn't match (absolute URLs,
 * data: URIs, etc.). Used by MarkdownRenderer and OpenUI components that
 * render images the bot wrote into the session's artifacts/ dir.
 *
 * `conversationId` is normally piped in from `useParams<{id}>()`; when
 * absent we fall back to parsing the current pathname so this works in
 * trees that mount outside the page's param scope (OpenUI components are
 * rendered via a dynamic CSR boundary that doesn't always see the route
 * params synchronously).
 */
export function resolveArtifactSrc(
  src: string | undefined,
  conversationId: string | undefined,
): string | undefined {
  if (!src) return src;
  const m = /^(?:\.?\/)?artifacts\/(.+)$/.exec(src);
  if (!m) return src;
  let convId = conversationId;
  if (!convId && globalThis.window !== undefined) {
    const pathMatch = /\/(?:[a-z]{2}(?:-[A-Z]{2})?\/)?c\/([^/?#]+)/.exec(
      globalThis.window.location.pathname,
    );
    if (pathMatch) convId = pathMatch[1];
  }
  if (!convId) return src;
  return sessionFilesApi.artifactUrl(convId, m[1]);
}

/**
 * Session workspace files. `artifacts/` (agent output) and `user-uploaded/`
 * attachments are served by the backend `/sessions` router. `listArtifacts`
 * is also the tab-focus reconcile path for missed live events.
 */
export const sessionFilesApi = {
  listArtifacts: (conversationId: string) =>
    apiService.get<ArtifactInfo[]>(`/sessions/${conversationId}/artifacts`, {
      silent: true,
    }),

  listUploads: (conversationId: string) =>
    apiService.get<ArtifactInfo[]>(`/sessions/${conversationId}/uploads`, {
      silent: true,
    }),

  artifactUrl: (conversationId: string, path: string) =>
    `${API_BASE}/sessions/${conversationId}/artifacts/${encodePath(path)}`,

  uploadUrl: (conversationId: string, path: string) =>
    `${API_BASE}/sessions/${conversationId}/uploads/${encodePath(path)}`,

  fetchArtifact: async (
    conversationId: string,
    path: string,
  ): Promise<string> => {
    const res = await apiauth.get<string>(
      `/sessions/${conversationId}/artifacts/${encodePath(path)}`,
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
