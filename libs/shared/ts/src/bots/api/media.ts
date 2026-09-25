/**
 * File upload, artifact download, and audio transcription for the GAIA bot API.
 *
 * Extracted from {@link GaiaClient} to keep multipart/binary file concerns out
 * of the JSON CRUD client. These are the raw HTTP requests; the caller wraps
 * them in its auth/retry helper (so a 401 retry recomputes the headers).
 *
 * @module
 */
import type { AxiosInstance } from "axios";
import type { BotFileData } from "../types";
import { fetchPublicAsset } from "../utils/public-fetch";

type Headers = Record<string, string>;

// 100 MB = the largest per-platform outbound cap (WhatsApp). A lower cap here
// would reject 50–100 MB artifacts as transport errors before
// OUTBOUND_FILE_LIMITS can apply the platform limit or graceful note.
const MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024;

/**
 * GETs binary bytes from GAIA's own API through the bot-authenticated client,
 * with the shared transport cap applied.
 *
 * `url` is a path on the API, or an absolute URL already proven to be on it by
 * `isOwnApiUrl` — axios skips `baseURL` for an absolute URL, so a base
 * carrying a path prefix cannot corrupt the target.
 */
export async function downloadApiBinaryRequest(
  client: AxiosInstance,
  headers: Headers,
  url: string,
): Promise<{ data: Buffer; contentType: string }> {
  const { data, headers: respHeaders } = await client.get(url, {
    responseType: "arraybuffer",
    headers,
    maxContentLength: MAX_DOWNLOAD_BYTES,
    maxBodyLength: MAX_DOWNLOAD_BYTES,
  });
  const contentType = String(
    respHeaders["content-type"] ?? "application/octet-stream",
  );
  return { data: Buffer.from(data as ArrayBuffer), contentType };
}

/**
 * Uploads a file to GAIA and returns its {@link BotFileData}, sendable with the
 * next chat request via `fileIds` / `fileData` so the agent grounds its reply.
 *
 * Uses the same `/api/v1/upload` endpoint as the web app — bot auth middleware
 * resolves the linked user from the platform headers.
 */
export async function uploadFileRequest(
  client: AxiosInstance,
  headers: Headers,
  input: {
    data: Buffer;
    filename: string;
    mimeType: string;
    conversationId?: string;
  },
): Promise<BotFileData> {
  const form = new FormData();
  // A File (not a Blob) preserves the mime type for FastAPI's UploadFile.content_type, which
  // file_service.py uses to dispatch image/PDF/text summarisation; File's 2-arg append also
  // keeps typings consistent under lib:ESNext, where the 3-arg FormData.append overload doesn't resolve.
  const file = new File([new Uint8Array(input.data)], input.filename, {
    type: input.mimeType,
  });
  form.append("file", file);
  if (input.conversationId) {
    form.append("conversation_id", input.conversationId);
  }

  const { data } = await client.post("/api/v1/upload", form, {
    headers: {
      ...headers,
      // The axios instance defaults Content-Type to application/json, which makes it JSON-encode
      // FormData instead of multipart (backend then sees no `file` field, returns 422). Force
      // multipart here — axios fills in the boundary from the FormData.
      "Content-Type": "multipart/form-data",
    },
    // Allow uploads up to the backend's 10 MB cap plus multipart overhead.
    maxBodyLength: 12 * 1024 * 1024,
    maxContentLength: 12 * 1024 * 1024,
  });

  return {
    fileId: data.fileId,
    url: data.url,
    filename: data.filename,
    type: data.type ?? "file",
    message: data.message,
  };
}

/**
 * Downloads a session artifact's bytes (a file the agent wrote to `artifacts/`)
 * so the bot can re-upload it via the platform's media API.
 *
 * Hits the same authenticated `GET /api/v1/sessions/{conv}/artifacts/{path}`
 * route the web app uses; the endpoint enforces conversation ownership.
 */
export async function downloadArtifactRequest(
  client: AxiosInstance,
  headers: Headers,
  conversationId: string,
  path: string,
): Promise<{ data: Buffer; contentType: string }> {
  const encodedPath = path
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
  return downloadApiBinaryRequest(
    client,
    headers,
    `/api/v1/sessions/${encodeURIComponent(conversationId)}/artifacts/${encodedPath}`,
  );
}

/**
 * Downloads bytes from a URL served by somebody other than GAIA — a step
 * screenshot published as a signed, short-lived object-store link.
 *
 * The URL is the whole authorization, so every hop is SSRF-guarded: a poisoned
 * queue entry must not make the bot read internal services. A URL on GAIA's own
 * API is the other case — see {@link downloadApiBinaryRequest}.
 */
export async function downloadUrlRequest(
  url: string,
): Promise<{ data: Buffer; contentType: string }> {
  return fetchPublicAsset(url, {
    maxContentLength: MAX_DOWNLOAD_BYTES,
    maxBodyLength: MAX_DOWNLOAD_BYTES,
  });
}

/**
 * Transcribes a short audio clip (voice note or audio file) to text via the bot
 * transcription endpoint, which proxies to OpenAI Whisper server-side.
 */
export async function transcribeAudioRequest(
  client: AxiosInstance,
  headers: Headers,
  input: {
    data: Buffer;
    filename: string;
    mimeType: string;
  },
): Promise<string> {
  const form = new FormData();
  const file = new File([new Uint8Array(input.data)], input.filename, {
    type: input.mimeType,
  });
  form.append("file", file);

  const { data } = await client.post("/api/v1/bot/transcribe", form, {
    headers: {
      ...headers,
      // Force multipart so axios doesn't JSON-encode the FormData (the instance
      // default Content-Type is application/json). See uploadFileRequest.
      "Content-Type": "multipart/form-data",
    },
    maxBodyLength: 30 * 1024 * 1024,
    maxContentLength: 30 * 1024 * 1024,
  });

  return String(data.text ?? "").trim();
}
