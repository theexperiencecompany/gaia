/**
 * The path-typed API client: every call is checked against the generated
 * `paths` from `apps/api/openapi.json`, so the path, its parameters, the
 * request body and the response type all come from the API itself.
 *
 *   const me = await api.get("/api/v1/user/me");           // AuthenticatedUserResponse
 *   await api.put("/api/v1/todos/{todo_id}", { path: { todo_id }, body });  // body: TodoUpdateRequest
 *   await api.get("/api/v1/todos", { query: { page: 2 } });
 *
 * It is a thin layer over `request` in ./service (same toasts, same error
 * handling): no generated runtime, only types. This is the only way feature
 * code talks to the API — `checks.mjs api-schema-types` fails a bare
 * `apiService.<method>(` outside lib/api.
 */
import type { paths } from "@shared/api/generated";
import { type ApiOptions, type QueryParams, request } from "./service";

type Method = "get" | "post" | "put" | "patch" | "delete";

/** Paths that declare `M` (openapi-typescript emits `post?: never` for the rest). */
type PathsWith<M extends Method> = {
  [P in keyof paths]: paths[P][M] extends undefined ? never : P;
}[keyof paths];

type Op<P extends keyof paths, M extends Method> = NonNullable<paths[P][M]>;

type SuccessCode = 200 | 201 | 202;

type JsonOf<R> = R extends { content: { "application/json": infer J } }
  ? J
  : unknown;

/** The 2xx body; `undefined` for a 204 or a route with no success body. */
type Res<O> = O extends { responses: infer R }
  ? [Extract<keyof R, SuccessCode>] extends [never]
    ? undefined
    : JsonOf<R[Extract<keyof R, SuccessCode>]>
  : never;

type BodyOf<C> = C extends { "application/json": infer J }
  ? J
  : C extends { "multipart/form-data": unknown }
    ? FormData
    : C extends { "application/x-www-form-urlencoded": unknown }
      ? URLSearchParams | FormData
      : never;

/** The request body: required, optional (`| undefined`), or `undefined` when the route takes none. */
type Body<O> = O extends { requestBody: { content: infer C } }
  ? BodyOf<C>
  : O extends { requestBody?: { content: infer C } }
    ? BodyOf<C> | undefined
    : undefined;

type PathParams<O> = O extends { parameters: { path: infer X } } ? X : never;

type Query<O> = O extends { parameters: { query?: infer Q } }
  ? Exclude<Q, undefined>
  : never;

type BodyPart<O> = [Body<O>] extends [undefined]
  ? { body?: never }
  : undefined extends Body<O>
    ? { body?: Body<O> }
    : { body: Body<O> };

type PathPart<O> = [PathParams<O>] extends [never]
  ? { path?: never }
  : { path: PathParams<O> };

type QueryPart<O> = [Query<O>] extends [never]
  ? { query?: never }
  : { query?: Query<O> };

/** Everything a call can carry: path params, query, body, and the toast options. */
export type Init<O> = ApiOptions & BodyPart<O> & PathPart<O> & QueryPart<O>;

/** `init` is mandatory exactly when the route needs a path parameter or a body. */
type InitArg<O> = [PathParams<O>] extends [never]
  ? undefined extends Body<O>
    ? [init?: Init<O>]
    : [init: Init<O>]
  : [init: Init<O>];

// The axios base URL already ends in /api/v1 (NEXT_PUBLIC_API_BASE_URL), so
// the schema path is trimmed to what the instance expects.
const API_PREFIX = "/api/v1";

function fill(
  path: string,
  params: Record<string, unknown> | undefined,
): string {
  const relative = path.slice(API_PREFIX.length);
  return relative.replace(/\{(\w+)\}/g, (_match, name: string) => {
    const value = params?.[name];
    if (value === undefined) {
      throw new Error(`api: path parameter "${name}" missing for ${path}`);
    }
    return encodeURIComponent(String(value));
  });
}

function call<P extends keyof paths, M extends Method>(
  method: M,
  path: P,
  init: Init<Op<P, M>> | undefined,
): Promise<Res<Op<P, M>>> {
  const { path: pathParams, query, body, ...options } = init ?? {};
  return request<Res<Op<P, M>>>(
    method.toUpperCase() as Uppercase<M>,
    fill(path, pathParams as Record<string, unknown> | undefined),
    body,
    options,
    query as QueryParams | undefined,
  );
}

export const api = {
  get: <P extends PathsWith<"get">>(
    path: P,
    ...[init]: InitArg<Op<P, "get">>
  ) => call("get", path, init),
  post: <P extends PathsWith<"post">>(
    path: P,
    ...[init]: InitArg<Op<P, "post">>
  ) => call("post", path, init),
  put: <P extends PathsWith<"put">>(
    path: P,
    ...[init]: InitArg<Op<P, "put">>
  ) => call("put", path, init),
  patch: <P extends PathsWith<"patch">>(
    path: P,
    ...[init]: InitArg<Op<P, "patch">>
  ) => call("patch", path, init),
  delete: <P extends PathsWith<"delete">>(
    path: P,
    ...[init]: InitArg<Op<P, "delete">>
  ) => call("delete", path, init),
};

/** The response type of `METHOD path`, for callers that store or pass one on. */
export type ApiResponse<M extends Method, P extends PathsWith<M>> = Res<
  Op<P, M>
>;

/** The request body type of `METHOD path`. */
export type ApiBody<M extends Method, P extends PathsWith<M>> = Body<Op<P, M>>;
