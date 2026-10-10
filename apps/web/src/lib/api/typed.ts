/**
 * The path-typed API client: every call is checked against the generated
 * `paths` from `apps/api/openapi.json`, so the path, its parameters, the
 * request body and the response type all come from the API itself.
 *
 *   const me = await api.get("/api/v1/user/me");           // AuthenticatedUserResponse
 *   await api.put("/api/v1/todos/{todo_id}", { path: { todo_id }, body });  // body: TodoUpdateRequest
 *   await api.get("/api/v1/search", { query: { query } });  // required query, checked
 *
 * The typing, the URL building and the body/response serialisation are
 * `openapi-fetch`'s — the companion of the `openapi-typescript` that generates
 * the schema. This module is the adapter: it lifts `params.path`/`params.query`
 * to the top level of the call, runs every request through the app's axios
 * instance (so the app-shell error handler, credentials and the timezone
 * header all still apply), and turns a non-2xx into an `ApiError`.
 *
 * This is the only way feature code talks to the API — `checks.mjs
 * api-schema-types` fails a bare `apiService.<method>(` outside lib/api.
 */
import { ApiError, REQUEST_ID_HEADER } from "@shared/api";
import type { paths } from "@shared/api/generated";
import axios from "axios";
import createClient, {
  type Client,
  type ClientPathsWithMethod,
  type FetchResponse,
  type MaybeOptionalInit,
} from "openapi-fetch";
import { apiauth, apiOrigin } from "./client";
import {
  type ApiOptions,
  announceSuccess,
  type HttpMethod,
  isHandled,
  reportFailure,
  toApiError,
} from "./outcome";

type Method = "get" | "post" | "put" | "patch" | "delete";
type MediaType = `${string}/${string}`;

type ApiClient = Client<paths>;

/** The paths that declare `M`, as openapi-fetch itself computes them. */
type PathsWith<M extends Method> = ClientPathsWithMethod<ApiClient, M> &
  keyof paths;

/** The 2xx body openapi-fetch resolves for the route; `undefined` for a 204. */
type Data<P extends keyof paths, M extends Method> = Extract<
  FetchResponse<NonNullable<paths[P][M]>, Record<never, never>, MediaType>,
  { data: unknown }
>["data"];

/**
 * openapi-fetch's own init, with `params.path` / `params.query` lifted to the
 * top level. Every required-ness decision — which paths take a body, which
 * query keys are mandatory — stays openapi-fetch's.
 */
type Lift<I> = I extends undefined
  ? never
  : Omit<NonNullable<I>, "params"> &
      (NonNullable<I> extends { params: infer X }
        ? X
        : NonNullable<I> extends { params?: infer X }
          ? Partial<X>
          : unknown);

type Init<P extends keyof paths, M extends Method> = Lift<
  MaybeOptionalInit<paths[P], M>
> &
  ApiOptions;

/** `init` is mandatory exactly when the route needs a parameter or a body. */
type InitArg<I> = Record<never, never> extends I ? [init?: I] : [init: I];

/** Statuses the Fetch spec forbids a body on. */
const BODILESS_STATUSES = new Set([204, 205, 304]);

/** Non-2xx responses, keyed to the axios error that produced them. */
const transportFailures = new WeakMap<Response, unknown>();

/** The axios payload as a body the Response constructor accepts. */
function toBodyInit(data: unknown): BodyInit | null {
  if (data === undefined || data === null) return null;
  return typeof data === "string" ? data : JSON.stringify(data);
}

function toResponse(result: {
  status?: number;
  data?: unknown;
  headers?: unknown;
}): Response {
  const status = result.status ?? 200;
  const headers = new Headers(
    (result.headers as Record<string, string> | undefined) ?? {},
  );
  const body = BODILESS_STATUSES.has(status) ? null : toBodyInit(result.data);
  return new Response(body, { status, headers });
}

const MULTIPART_PREFIX = "multipart/form-data";

/** The serialised body openapi-fetch built, read back off the Request. */
async function readBody(request: Request): Promise<unknown> {
  if (request.body === null || request.method === "GET") return undefined;
  if (request.headers.get("content-type")?.startsWith(MULTIPART_PREFIX)) {
    return request.formData();
  }
  return request.text();
}

/**
 * Run an openapi-fetch request through the app's axios instance.
 *
 * Everything the instance owns — credentials, the timezone header, the global
 * timeout and the app-shell response handler — therefore applies to typed
 * calls exactly as it does to `apiService` ones. The payload is left to axios's
 * default parsing so the error handler still sees the body it branches on.
 */
async function axiosFetch(request: Request): Promise<Response> {
  const data = await readBody(request);
  // axios must set its own multipart boundary; the one openapi-fetch's
  // Request produced belongs to a body we have already re-read.
  const dropContentType = data instanceof FormData;
  const headers = Object.fromEntries(
    [...request.headers.entries()].filter(
      ([name]) => !(dropContentType && name === "content-type"),
    ),
  );

  try {
    return toResponse(
      await apiauth.request({
        method: request.method,
        url: request.url,
        data,
        headers,
        signal: request.signal,
      }),
    );
  } catch (error) {
    const response = axios.isAxiosError(error) ? error.response : undefined;
    // No response at all (network failure, timeout, abort) is not an HTTP
    // outcome — let it reach the caller as the thrown error it is.
    if (!response) throw error;
    const built = toResponse(response);
    transportFailures.set(built, error);
    return built;
  }
}

const client = createClient<paths>({ baseUrl: apiOrigin, fetch: axiosFetch });

/** What openapi-fetch resolves to, before the envelope becomes an ApiError. */
interface CallResult {
  data?: unknown;
  error?: unknown;
  response: Response;
}

async function call<R>(
  method: Method,
  path: string,
  init?: object,
): Promise<R> {
  const {
    path: pathParams,
    query,
    body,
    successMessage,
    errorMessage,
    silent,
    ...fetchOptions
  } = (init ?? {}) as ApiOptions & Record<string, unknown>;
  const options: ApiOptions = { successMessage, errorMessage, silent };
  const httpMethod = method.toUpperCase() as HttpMethod;

  let result: CallResult;
  try {
    result = (await client.request(
      method,
      path as never,
      {
        ...fetchOptions,
        params: { path: pathParams, query },
        body,
      } as never,
    )) as CallResult;
  } catch (error) {
    throw reportFailure(
      httpMethod,
      String(path),
      toApiError(error),
      options,
      isHandled(error),
    );
  }

  const { response } = result;
  if (!response.ok) {
    // openapi-fetch has already parsed the error body; the axios error is kept
    // only for the `handled` flag the app-shell handler set on it.
    const cause = transportFailures.get(response);
    throw reportFailure(
      httpMethod,
      response.url || String(path),
      ApiError.fromBody(response.status, result.error, {
        fallbackMessage: cause instanceof Error ? cause.message : undefined,
        requestId: response.headers.get(REQUEST_ID_HEADER) ?? undefined,
        cause,
      }),
      options,
      isHandled(cause),
    );
  }

  announceSuccess(options);
  return result.data as R;
}

export const api = {
  get: <P extends PathsWith<"get">>(
    path: P,
    ...[init]: InitArg<Init<P, "get">>
  ) => call<Data<P, "get">>("get", path, init),
  post: <P extends PathsWith<"post">>(
    path: P,
    ...[init]: InitArg<Init<P, "post">>
  ) => call<Data<P, "post">>("post", path, init),
  put: <P extends PathsWith<"put">>(
    path: P,
    ...[init]: InitArg<Init<P, "put">>
  ) => call<Data<P, "put">>("put", path, init),
  patch: <P extends PathsWith<"patch">>(
    path: P,
    ...[init]: InitArg<Init<P, "patch">>
  ) => call<Data<P, "patch">>("patch", path, init),
  delete: <P extends PathsWith<"delete">>(
    path: P,
    ...[init]: InitArg<Init<P, "delete">>
  ) => call<Data<P, "delete">>("delete", path, init),
  /**
   * GET a route whose body is not JSON — a file download, a rendered artifact.
   * The schema declares no content for these, so the parse mode says what
   * comes back instead of the response type.
   */
  text: <P extends PathsWith<"get">>(
    path: P,
    ...[init]: InitArg<Init<P, "get">>
  ) => call<string>("get", path, { ...init, parseAs: "text" }),
};

/**
 * Serialise a multipart body — the schema's own object type, not a hand-built
 * FormData. Pass as `bodySerializer` on the routes that declare
 * `multipart/form-data`; array values become repeated fields.
 */
export function formDataSerializer(body: unknown): FormData {
  const form = new FormData();
  for (const [key, value] of Object.entries(
    (body ?? {}) as Record<string, unknown>,
  )) {
    if (value === undefined || value === null) continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      form.append(key, item instanceof Blob ? item : String(item));
    }
  }
  return form;
}

/** The header that makes openapi-fetch url-encode a form body. */
export const FORM_URLENCODED_HEADERS = {
  "Content-Type": "application/x-www-form-urlencoded",
} as const;

/**
 * A File for a multipart field.
 *
 * openapi-typescript types a `format: binary` field as `string` and offers no
 * option to emit Blob, so the File the browser must send needs saying so here
 * rather than at every upload call site.
 */
export const binaryField = (file: File): string =>
  file as unknown as string; /* the generator's `string` is the wire's binary */

/** The response type of `METHOD path`, for callers that store or pass one on. */
export type ApiResponse<M extends Method, P extends PathsWith<M>> = Data<P, M>;

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
