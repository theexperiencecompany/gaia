/**
 * The one error every GAIA API consumer throws and catches.
 *
 * The backend answers every 4xx/5xx with the flat `ErrorEnvelope`
 * (`apps/api/app/schemas/errors.py`): `{ message, code?, why?, fix?, errors? }`.
 * This carries that envelope, already narrowed, so a caller branches on
 * `error.envelope?.code` instead of re-parsing an `unknown` body.
 */

import type { ErrorEnvelope } from "./generated/index.js";

export type { ErrorEnvelope };

/** Identifies the request in the API's logs; set by the API gateway. */
export const REQUEST_ID_HEADER = "x-request-id";

/**
 * Narrow a response body to the API's error envelope.
 *
 * Answers undefined for anything that carries neither half of the envelope —
 * a proxy's HTML page, a network artefact, an empty body.
 */
export function toErrorEnvelope(body: unknown): ErrorEnvelope | undefined {
  if (!body || typeof body !== "object") return undefined;
  const { message, code } = body as { message?: unknown; code?: unknown };
  if (typeof message !== "string" && typeof code !== "string") return undefined;
  return body as ErrorEnvelope;
}

interface ApiErrorInit {
  /** The parsed envelope, when the body was one. */
  envelope?: ErrorEnvelope | undefined;
  /** The response body as received, for bodies that are not an envelope. */
  body?: string | undefined;
  /** The API's request id, when the response carried one. */
  requestId?: string | undefined;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly envelope: ErrorEnvelope | undefined;
  readonly body: string;
  readonly requestId: string | undefined;

  constructor(message: string, status: number, init: ApiErrorInit = {}) {
    super(
      message,
      init.cause === undefined ? undefined : { cause: init.cause },
    );
    this.name = "ApiError";
    this.status = status;
    this.envelope = init.envelope;
    this.body = init.body ?? "";
    this.requestId = init.requestId;
  }

  /** The backend's machine-readable error code, when it sent one. */
  get code(): string | undefined {
    const code = this.envelope?.code;
    return typeof code === "string" ? code : undefined;
  }

  /**
   * Build the error from a response body of any shape.
   *
   * The message is the envelope's own words when the body is an envelope, so
   * the backend's copy reaches the user instead of a status line.
   */
  static fromBody(
    status: number,
    body: unknown,
    init: {
      fallbackMessage?: string | undefined;
      requestId?: string | undefined;
      cause?: unknown;
    } = {},
  ): ApiError {
    const envelope = toErrorEnvelope(body);
    const message =
      envelope?.message ??
      init.fallbackMessage ??
      `API request failed: ${status}`;
    return new ApiError(message, status, {
      envelope,
      body: typeof body === "string" ? body : JSON.stringify(body ?? ""),
      requestId: init.requestId,
      cause: init.cause,
    });
  }
}
