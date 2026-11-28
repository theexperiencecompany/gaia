import { Context, Effect, Layer, Schema } from "effect";

/** A failed API call, with the status the server returned. */
export class ApiError extends Schema.TaggedError<ApiError>()("ApiError", {
  status: Schema.Number,
  message: Schema.String,
}) {}

export interface ApiShape {
  readonly request: <A>(
    path: string,
    init: RequestInit,
    schema: Schema.Codec<A>,
  ) => Effect.Effect<A, ApiError>;
}

/**
 * The only HTTP surface a page uses. It is a service so a test can replace it,
 * and so the host (Next or Vite) owns the base URL.
 */
export class Api extends Context.Service<Api, ApiShape>()("Api") {}

const toApiError = (cause: unknown): ApiError =>
  cause instanceof ApiError
    ? cause
    : new ApiError({ status: 0, message: String(cause) });

/**
 * Binds the API to a base URL. The caller passes a URL that already includes
 * `/api/v1`, e.g. `http://localhost:8000/api/v1`.
 */
export const ApiLive = (baseUrl: string) =>
  Layer.succeed(
    Api,
    Api.of({
      request: (path, init, schema) =>
        Effect.gen(function* () {
          const response = yield* Effect.tryPromise({
            try: () =>
              fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
                credentials: "include",
                ...init,
                headers: {
                  "content-type": "application/json",
                  ...(init.headers ?? {}),
                },
              }),
            catch: toApiError,
          });

          if (!response.ok) {
            const body = yield* Effect.tryPromise({
              try: () => response.text(),
              catch: toApiError,
            }).pipe(Effect.orElseSucceed(() => ""));
            return yield* Effect.fail(
              new ApiError({
                status: response.status,
                message: body || response.statusText,
              }),
            );
          }

          const json = yield* Effect.tryPromise({
            try: () => response.json() as Promise<unknown>,
            catch: toApiError,
          });

          return yield* Effect.try({
            try: () => Schema.decodeUnknownSync(schema)(json),
            catch: toApiError,
          });
        }),
    }),
  );
