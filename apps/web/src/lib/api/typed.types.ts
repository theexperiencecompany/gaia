/** The types the path-typed client (typed.ts) is written in, and the ones its callers name. */
import type { paths } from "@shared/api/generated";
import type {
  Client,
  ClientPathsWithMethod,
  FetchResponse,
} from "openapi-fetch";

import type { ApiOptions } from "./outcome";

export type Method = "get" | "post" | "put" | "patch" | "delete";
type MediaType = `${string}/${string}`;

type ApiClient = Client<paths>;

/** The paths that declare `M`, as openapi-fetch itself computes them. */
export type PathsWith<M extends Method> = ClientPathsWithMethod<ApiClient, M> &
  keyof paths;

/** The 2xx body openapi-fetch resolves for the route; `undefined` for a 204. */
export type Data<P extends keyof paths, M extends Method> = Extract<
  FetchResponse<NonNullable<paths[P][M]>, Record<never, never>, MediaType>,
  { data: unknown }
>["data"];

/** Who caused a request, for an API function that is called both by a user and by a poll. */
export type RequestOrigin = Pick<ApiOptions, "background">;

/** The response type of `METHOD path`, for callers that store or pass one on. */
export type ApiResponse<M extends Method, P extends PathsWith<M>> = Data<P, M>;

/** The query parameters of `METHOD path`, for an API function that forwards them. */
export type ApiQuery<M extends Method, P extends PathsWith<M>> = NonNullable<
  NonNullable<paths[P][M]> extends { parameters: { query?: infer Q } }
    ? Q
    : never
>;

/**
 * The request body type of `METHOD path` — whichever media type the route
 * declares, read straight off the schema rather than through the call init,
 * which is far more expensive for the compiler to unwrap.
 */
export type ApiBody<M extends Method, P extends PathsWith<M>> =
  NonNullable<paths[P][M]> extends { requestBody?: infer R }
    ? NonNullable<R> extends { content: infer C }
      ? C[keyof C]
      : never
    : never;
