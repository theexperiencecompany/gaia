/**
 * Narrowing for the API's one error shape. Every non-2xx body the backend
 * emits is the flat `{ message, code?, ... }` envelope (`ErrorEnvelope` in
 * apps/api/app/schemas/errors.py); anything else is a proxy or network
 * artefact, and these helpers answer `undefined` for it.
 */

interface ErrorBody {
  message?: unknown;
  code?: unknown;
  fix?: unknown;
}

const asErrorBody = (data: unknown): ErrorBody | undefined =>
  data && typeof data === "object" ? (data as ErrorBody) : undefined;

/** The machine-readable `code` of an error envelope, if the body is one. */
export const getErrorCode = (data: unknown): string | undefined => {
  const code = asErrorBody(data)?.code;
  return typeof code === "string" ? code : undefined;
};

/**
 * The human-readable `message` of an error envelope, or undefined when the
 * body is not one (so callers fall back to their own default copy).
 */
export const getErrorMessage = (data: unknown): string | undefined => {
  const message = asErrorBody(data)?.message;
  return typeof message === "string" ? message : undefined;
};

/**
 * The remediation hint an envelope carries alongside its message ("Ask the
 * bot for a fresh link."). Worth rendering: it is the half of the error that
 * tells the user what to do next.
 */
export const getErrorFix = (data: unknown): string | undefined => {
  const fix = asErrorBody(data)?.fix;
  return typeof fix === "string" ? fix : undefined;
};
