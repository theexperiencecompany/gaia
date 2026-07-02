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

type Headers = Record<string, string>;

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
  // A File (carrying name + type) preserves the mime type for FastAPI's
  // UploadFile content_type, which file_service.py uses to dispatch
  // image/PDF/text summarisation. A File with a 2-arg append (vs a Blob with a
  // 3-arg append) keeps the typings consistent under lib:ESNext, where the
  // 3-arg FormData.append overload isn't resolved.
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
      // The axios instance defaults Content-Type to application/json, which
      // makes axios JSON-encode FormData instead of sending multipart (the
      // backend then sees no `file` field and returns 422). Force multipart
      // here — axios fills in the boundary from the FormData.
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
  const { data, headers: respHeaders } = await client.get(
    `/api/v1/sessions/${encodeURIComponent(conversationId)}/artifacts/${encodedPath}`,
    {
      responseType: "arraybuffer",
      headers,
      // 100 MB = the largest per-platform outbound cap (WhatsApp). A lower cap
      // here would reject 50–100 MB artifacts as transport errors before
      // OUTBOUND_FILE_LIMITS can apply the platform limit or graceful note.
      maxContentLength: 100 * 1024 * 1024,
      maxBodyLength: 100 * 1024 * 1024,
    },
  );
  const contentType = String(
    respHeaders["content-type"] ?? "application/octet-stream",
  );
  return { data: Buffer.from(data as ArrayBuffer), contentType };
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
