import type { PathSerializer } from "openapi-fetch";
import { apiBaseUrl } from "@/lib/api/client";
import { api } from "@/lib/api/typed";

function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

/**
 * `{path}` is a FastAPI path converter: its slashes separate segments rather
 * than being data, so it is encoded per segment instead of whole.
 */
const nestedPathSerializer: PathSerializer = (pathname, pathParams) =>
  pathname.replace(/\{(\w+)\}/g, (_match, name: string) => {
    const value = String(pathParams[name]);
    return name === "path" ? encodePath(value) : encodeURIComponent(value);
  });

/**
 * Rewrite bot-emitted artifact paths (./artifacts/foo, /artifacts/foo,
 * artifacts/foo) to the auth-gated backend URL for this conversation;
 * returns the original src for anything else. Used by MarkdownRenderer and
 * OpenUI for images the bot wrote into artifacts/. `conversationId` falls
 * back to parsing the pathname when `useParams` doesn't see it (OpenUI's
 * dynamic CSR boundary can mount outside the page's param scope).
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
    api.get("/api/v1/sessions/{conv_id}/artifacts", {
      path: { conv_id: conversationId },
      silent: true,
    }),

  listUploads: (conversationId: string) =>
    api.get("/api/v1/sessions/{conv_id}/uploads", {
      path: { conv_id: conversationId },
      silent: true,
    }),

  artifactUrl: (conversationId: string, path: string) =>
    `${apiBaseUrl}/sessions/${conversationId}/artifacts/${encodePath(path)}`,

  uploadUrl: (conversationId: string, path: string) =>
    `${apiBaseUrl}/sessions/${conversationId}/uploads/${encodePath(path)}`,

  // The route serves the file itself, so the schema declares no response body;
  // `api.text` says what comes back instead.
  fetchArtifact: (conversationId: string, path: string): Promise<string> =>
    api.text("/api/v1/sessions/{conv_id}/artifacts/{path}", {
      path: { conv_id: conversationId, path },
      pathSerializer: nestedPathSerializer,
      silent: true,
    }),

  pin: (conversationId: string, path: string, targetName?: string) =>
    api.post("/api/v1/sessions/{conv_id}/pin", {
      path: { conv_id: conversationId },
      body: { path, target_name: targetName },
    }),
};
